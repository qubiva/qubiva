import logging
import os
import traceback
import asyncio
from datetime import datetime, timedelta, timezone
from kubernetes import client as k8s_client, config as k8s_config

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class DiscoveryJobTrigger:
    DEFAULT_TIMEOUT_HOURS = 2

    def __init__(self, request_tracker, request_id, config_manager, log_persistence=None, pool_manager=None):
        self.namespace = os.environ.get('K8S_NAMESPACE', 'default')
        self.job_image = os.environ.get('DISCOVERY_RUNNER_IMAGE', 'qubiva/discovery-runner:latest')
        self.job_ttl_seconds = int(os.environ.get('JOB_TTL_SECONDS_AFTER_FINISHED', '3600'))
        self.request_tracker = request_tracker
        self.request_id = request_id
        self.config_manager = config_manager
        self.log_persistence = log_persistence
        self.pool_manager = pool_manager
        self._init_k8s_client()

    def _init_k8s_client(self):
        """Initialize Kubernetes client (in-cluster or local kubeconfig)"""
        try:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            # kubernetes-python-client v29+ bug: auth_settings() checks
            # api_key['BearerToken'] but load_incluster_config() writes
            # api_key['authorization'], so no auth header is sent (system:anonymous).
            # Fix: wrap the refresh hook to keep both keys in sync.
            cfg = k8s_client.Configuration.get_default_copy()
            if 'authorization' in cfg.api_key and 'BearerToken' not in cfg.api_key:
                orig_hook = cfg.refresh_api_key_hook

                def _make_hook(h):
                    def _hook(c):
                        if h:
                            h(c)
                        if 'authorization' in c.api_key:
                            c.api_key['BearerToken'] = c.api_key['authorization']
                    return _hook
                cfg.refresh_api_key_hook = _make_hook(orig_hook)
                cfg.refresh_api_key_hook(cfg)
            api_client = k8s_client.ApiClient(configuration=cfg)
            self.batch_v1 = k8s_client.BatchV1Api(api_client=api_client)
            self.core_v1 = k8s_client.CoreV1Api(api_client=api_client)
        except k8s_config.ConfigException:
            logger.warning("No Kubernetes config found — discovery executor disabled")
            self.batch_v1 = None
            self.core_v1 = None

    async def stop_task(self, job_name, reason="Job timed out"):
        """Stop a running Kubernetes Job"""
        try:
            self.batch_v1.delete_namespaced_job(
                name=job_name,
                namespace=self.namespace,
                body=k8s_client.V1DeleteOptions(propagation_policy='Foreground')
            )
            logger.info(f"Job {job_name} deleted successfully")
            return True
        except Exception as e:
            error_msg = f"Failed to stop K8s job: {str(e)}"
            await self.request_tracker.update_error_details(self.request_id, error_msg)
            logger.error(f"Error stopping job {job_name}: {str(e)}")
            return False

    async def _persist_logs(self, job_name, request_id, project_name):
        """Fetch pod logs and push to Loki for long-term storage."""
        if not self.log_persistence:
            return
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f'job-name={job_name}'
            )
            if not pods.items:
                logger.debug(f"No pods found for job {job_name}, skipping log persistence")
                return

            pod_name = pods.items[0].metadata.name
            try:
                log_text = self.core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=self.namespace,
                    container='discovery-runner',
                    tail_lines=50000,
                )
            except k8s_client.ApiException:
                logger.debug(f"Could not fetch pod logs for {pod_name}, pod may already be deleted")
                return

            if log_text:
                await self.log_persistence.push_logs(
                    request_id=request_id,
                    job_type='discovery',
                    project_name=project_name,
                    log_text=log_text,
                )
        except Exception as e:
            logger.warning(f"Failed to persist logs for {request_id}: {e}")

    async def monitor_task_status(self, job_name, request_id, project_name, poll_interval=30, grace_period=60, timeout_hours=None):
        """Monitor a K8s Job until completion, failure, or timeout"""
        try:
            success, request_details = await self.request_tracker.get_request_details(request_id)
            if not success:
                await self.request_tracker.update_error_details(request_id, f"Failed to fetch request details: {request_details}")
                return

            requested_on_str = request_details.get("requested_on")
            request_state = request_details.get("state")

            if not requested_on_str or not request_state:
                await self.request_tracker.update_error_details(request_id, "Missing required request details")
                return

            requested_on = datetime.fromisoformat(requested_on_str)
            timeout_hours = timeout_hours or self.DEFAULT_TIMEOUT_HOURS
            timeout_time = requested_on + timedelta(hours=timeout_hours)

            while datetime.now(timezone.utc) < timeout_time:
                success, updated = await self.request_tracker.get_request_details(request_id)
                if success:
                    state = updated.get("state")
                    if state in ["completed", "benchmark succeeded", "benchmark failed", "execution failed", "timed out", "cancelled"]:
                        logger.info(f"Request {request_id} reached terminal state: {state}")
                        return

                try:
                    job = self.batch_v1.read_namespaced_job_status(name=job_name, namespace=self.namespace)

                    if job.status.succeeded and job.status.succeeded > 0:
                        await asyncio.sleep(grace_period)
                        success, final = await self.request_tracker.get_request_details(request_id)
                        if success and final.get("state") not in ["completed", "benchmark succeeded", "benchmark failed", "execution failed", "cancelled"]:
                            await self.request_tracker.update_request_state(request_id, "completed")
                        return

                    if job.status.failed and job.status.failed > 0:
                        await asyncio.sleep(grace_period)
                        success, final = await self.request_tracker.get_request_details(request_id)
                        if success and final.get("state") not in ["completed", "benchmark succeeded", "benchmark failed", "execution failed", "cancelled"]:
                            await self.request_tracker.update_error_details(request_id, "Run failed")
                            await self.request_tracker.update_request_state(request_id, "execution failed")
                        return

                    # Check pod status for fatal container states that the Job
                    # controller doesn't count as "failed" (e.g. ErrImagePull)
                    pod_error = await self._check_pod_fatal_state(job_name)
                    if pod_error:
                        logger.warning(f"Pod fatal state detected for {job_name}: {pod_error}")
                        await self.request_tracker.update_error_details(request_id, pod_error)
                        await self.request_tracker.update_request_state(request_id, "execution failed")
                        await self.stop_task(job_name, reason=pod_error)
                        return

                except k8s_client.ApiException as e:
                    if e.status == 404:
                        await asyncio.sleep(grace_period)
                        success, final = await self.request_tracker.get_request_details(request_id)
                        if success and final.get("state") not in ["completed", "benchmark succeeded", "benchmark failed", "execution failed", "timed out"]:
                            await self.request_tracker.update_error_details(request_id, "Run was interrupted unexpectedly")
                            await self.request_tracker.update_request_state(request_id, "execution failed")
                        return
                    else:
                        logger.warning(f"K8s API error monitoring job {job_name}: {e.status} {e.reason}")

                await asyncio.sleep(poll_interval)

            # Timeout
            await self.request_tracker.update_error_details(request_id, f"Job exceeded timeout of {timeout_hours} hours")
            await self.stop_task(job_name)
            await self.request_tracker.update_request_state(request_id, "timed out")

        except Exception as e:
            await self.request_tracker.update_error_details(request_id, f"Error monitoring job: {str(e)}")
            logger.error(f"Error monitoring job {job_name}: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            await self._persist_logs(job_name, request_id, project_name)

    async def _check_pod_fatal_state(self, job_name: str) -> str:
        """Check if any pod for this job is in a fatal state that won't resolve on its own.
        Returns error message string if fatal, None otherwise."""
        fatal_reasons = {
            'ErrImagePull', 'ImagePullBackOff', 'InvalidImageName',
            'CrashLoopBackOff', 'CreateContainerConfigError',
            'RunContainerError', 'ErrImageNeverPull',
        }
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f'job-name={job_name}'
            )
            for pod in pods.items:
                if not pod.status or not pod.status.container_statuses:
                    continue
                for cs in pod.status.container_statuses:
                    if cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason or ''
                        if reason in fatal_reasons:
                            message = cs.state.waiting.message or reason
                            return f"Run environment failed to initialize: {message}"
        except Exception as e:
            logger.debug(f"Error checking pod state for {job_name}: {e}")
        return None

    async def trigger_discovery_command(
        self,
        project_name,
        run_details,
        run_type,
        request_id,
        cloud_platform,
        query_engine_version,
        compliance_engine_version,
        plugin_version,
        use_auto_benchmark=False,
        github_repo=None,
        timeout_hours=None,
        mod_type=None,
        benchmark_id=None,
        mod_github_url=None,
        mod_name=None,
    ):
        try:
            await self.request_tracker.update_request_state(self.request_id, "queued")

            required_fields = {
                'project_name': project_name,
                'run_type': run_type,
                'cloud_platform': cloud_platform
            }

            for field, value in required_fields.items():
                if not value:
                    error_msg = f"Required field '{field}' is missing"
                    await self.request_tracker.update_error_details(self.request_id, error_msg)
                    await self.request_tracker.update_request_state(self.request_id, "failed")
                    return {'status': 'error', 'error': error_msg}

            # Build environment variables
            env_vars = [
                {"name": "PROJECT_NAME", "value": str(project_name)},
                {"name": "REQUEST_ID", "value": str(request_id)},
                {"name": "RUN_TYPE", "value": str(run_type)},
                {"name": "CLOUD_PLATFORM", "value": str(cloud_platform)},
                {"name": "QUERY_ENGINE_VERSION", "value": str(query_engine_version)},
                {"name": "COMPLIANCE_ENGINE_VERSION", "value": str(compliance_engine_version)},
                {"name": "PLUGIN_VERSION", "value": str(plugin_version)},
                {"name": "USE_AUTO_BENCHMARK", "value": "true" if use_auto_benchmark else "false"},
            ]

            if use_auto_benchmark and mod_type and benchmark_id:
                env_vars.append({"name": "MOD_TYPE", "value": str(mod_type)})
                env_vars.append({"name": "BENCHMARK_ID", "value": str(benchmark_id)})
                env_vars.append({"name": "MOD_GITHUB_URL", "value": str(mod_github_url)})
                env_vars.append({"name": "MOD_NAME", "value": str(mod_name)})

            artifacts_path = os.environ.get("ARTIFACTS_STORAGE_PATH")
            artifacts_prefix = os.environ.get("ARTIFACTS_PREFIX")
            if artifacts_path:
                env_vars.append({"name": "ARTIFACTS_STORAGE_PATH", "value": artifacts_path})
            if artifacts_prefix:
                env_vars.append({"name": "ARTIFACTS_PREFIX", "value": artifacts_prefix})

            api_endpoint = os.environ.get("QUBIVA_API_ENDPOINT")
            if api_endpoint:
                env_vars.append({"name": "QUBIVA_API_ENDPOINT", "value": str(api_endpoint)})

            if github_repo:
                repo_url = github_repo.get("repo_url")
                if repo_url:
                    env_vars.append({"name": "GITHUB_REPO_URL", "value": str(repo_url)})
                branch = github_repo.get("branch", "main")
                if branch:
                    env_vars.append({"name": "GITHUB_BRANCH", "value": str(branch)})
                token = github_repo.get("token")
                if token is not None and token != "":
                    env_vars.append({"name": "GITHUB_TOKEN", "value": str(token)})

                if run_type == "query":
                    queries_path = github_repo.get("discovery_queries_path")
                    if queries_path:
                        env_vars.append({"name": "CLOUD_QUERIES_PATH", "value": str(queries_path)})
                elif run_type == "benchmark" and not use_auto_benchmark:
                    benchmark_path = github_repo.get("custom_benchmark_path")
                    if benchmark_path:
                        env_vars.append({"name": "CUSTOM_BENCHMARK_PATH", "value": str(benchmark_path)})

            if "auth_env_vars" in run_details:
                for key, value in run_details["auth_env_vars"].items():
                    if value is not None and value != "":
                        env_vars.append({"name": key, "value": str(value)})

            # Pass internal API key for authenticated callbacks to Qubiva
            internal_api_key = os.environ.get("INTERNAL_API_KEY")
            if internal_api_key:
                env_vars.append({"name": "INTERNAL_API_KEY", "value": internal_api_key})

            cloud_account_id = run_details.get("cloud_account_id", "")
            if cloud_account_id:
                env_vars.append({"name": "CLOUD_ACCOUNT_ID", "value": str(cloud_account_id)})

            # ── Pool-first execution path ─────────────────────────
            if self.pool_manager:
                pod = self.pool_manager.claim_pod(request_id, project_name=project_name)
                if pod:
                    inject_result = await self.pool_manager.inject_env_and_execute(pod, env_vars)
                    if not inject_result.get("error"):
                        await self.request_tracker.update_job_name(request_id, pod.pod_name)
                        success, message = await self.request_tracker.update_log_stream(
                            request_id, pod.pod_name, "discovery-runner"
                        )
                        if not success:
                            logger.error(f"Failed to update log stream: {message}")

                        asyncio.create_task(
                            self.pool_manager.monitor_execution(
                                pod=pod,
                                request_id=request_id,
                                request_tracker=self.request_tracker,
                                project_name=project_name,
                                log_persistence=self.log_persistence,
                                timeout_hours=timeout_hours or self.DEFAULT_TIMEOUT_HOURS,
                            )
                        )
                        await self.request_tracker.update_request_state(self.request_id, "in progress")

                        logger.info(f"Discovery execution started via pool pod: {pod.pod_name}")
                        return {
                            "status": "success",
                            "task_arn": pod.pod_name,
                            "log_stream_name": f"{pod.pod_name}:discovery-runner",
                        }
                    else:
                        logger.warning(
                            "Pool pod injection failed for %s, falling back to Job: %s",
                            pod.pod_name, inject_result.get("error"),
                        )

            # In pool_only mode, reject the job if no pool runner was available
            if self.pool_manager and self.pool_manager.get_execution_mode() == "pool_only":
                msg = "No runners available. All runners are currently busy — your job will run as soon as one frees up. Please try again shortly."
                logger.info("pool_only mode: no runner available for request %s", request_id)
                await self.request_tracker.update_request_state(request_id, "failed")
                await self.request_tracker.update_error_details(request_id, msg)
                return {'status': 'error', 'error': msg}

            # Create Kubernetes Job with PVC mount for artifacts (fallback)
            job_name = f"sp-{request_id[:20].lower().replace('_', '-')}"
            k8s_env = [k8s_client.V1EnvVar(name=e['name'], value=e['value']) for e in env_vars]

            # Mount artifacts PVC so runner can write results directly
            volume_mounts = [
                k8s_client.V1VolumeMount(
                    name='artifacts-storage',
                    mount_path=os.environ.get('ARTIFACTS_STORAGE_PATH', '/app/data/artifacts')
                )
            ]

            volumes = [
                k8s_client.V1Volume(
                    name='artifacts-storage',
                    persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                        claim_name='qubiva-artifacts'
                    )
                )
            ]

            container = k8s_client.V1Container(
                name='discovery-runner',
                image=self.job_image,
                image_pull_policy='IfNotPresent',
                env=k8s_env,
                volume_mounts=volume_mounts,
                resources=k8s_client.V1ResourceRequirements(
                    requests={'memory': '512Mi', 'cpu': '250m'},
                    limits={'memory': '2Gi', 'cpu': '1'}
                )
            )

            job = k8s_client.V1Job(
                api_version='batch/v1',
                kind='Job',
                metadata=k8s_client.V1ObjectMeta(
                    name=job_name,
                    namespace=self.namespace,
                    labels={
                        'app': 'qubiva',
                        'component': 'discovery-runner',
                        'request-id': request_id[:63],
                    }
                ),
                spec=k8s_client.V1JobSpec(
                    template=k8s_client.V1PodTemplateSpec(
                        metadata=k8s_client.V1ObjectMeta(
                            labels={
                                'app': 'qubiva',
                                'component': 'discovery-runner',
                            }
                        ),
                        spec=k8s_client.V1PodSpec(
                            containers=[container],
                            volumes=volumes,
                            restart_policy='Never',
                            service_account_name=os.environ.get('RUNNER_SERVICE_ACCOUNT', 'qubiva-runner'),
                        )
                    ),
                    backoff_limit=0,
                    ttl_seconds_after_finished=self.job_ttl_seconds,
                )
            )

            self.batch_v1.create_namespaced_job(namespace=self.namespace, body=job)
            logger.info(f"Discovery K8s job created: {job_name}")

            # Store job name in request for stop/cancel support
            await self.request_tracker.update_job_name(request_id, job_name)

            # Get pod name for log streaming
            await asyncio.sleep(2)
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f'job-name={job_name}'
            )
            pod_name = pods.items[0].metadata.name if pods.items else job_name

            log_ref = f"{pod_name}:discovery-runner"
            success, message = await self.request_tracker.update_log_stream(request_id, pod_name, "discovery-runner")
            if not success:
                logger.error(f"Failed to update log stream: {message}")

            asyncio.create_task(self.monitor_task_status(job_name, request_id, project_name, timeout_hours=timeout_hours))
            await self.request_tracker.update_request_state(self.request_id, "in progress")

            return {
                "status": "success",
                "task_arn": job_name,
                "log_stream_name": log_ref,
            }

        except Exception as e:
            error_msg = f"Unexpected error in discovery execution: {str(e)}"
            await self.request_tracker.update_error_details(self.request_id, error_msg)
            await self.request_tracker.update_request_state(self.request_id, "failed")
            logger.error(f"Error in trigger_discovery_command: {str(e)}")
            logger.error(traceback.format_exc())
            return {"status": "error", "error": error_msg}
