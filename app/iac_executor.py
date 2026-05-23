import logging
import os
import traceback
import asyncio
import urllib.parse
from datetime import datetime, timedelta, timezone
from kubernetes import client as k8s_client, config as k8s_config

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class IaCJobTrigger:
    DEFAULT_TIMEOUT_HOURS = 6

    def __init__(self, request_tracker, request_id, project_manager, log_persistence=None, pool_manager=None, config_manager=None):
        self.namespace = os.environ.get('K8S_NAMESPACE', 'default')
        self.job_image = os.environ.get('IAC_RUNNER_IMAGE', 'qubiva/iac-runner:latest')
        self.job_ttl_seconds = int(os.environ.get('JOB_TTL_SECONDS_AFTER_FINISHED', '3600'))
        self.request_tracker = request_tracker
        self.request_id = request_id
        self.project_manager = project_manager
        self.log_persistence = log_persistence
        self.pool_manager = pool_manager
        self.config_manager = config_manager
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
            logger.warning("No Kubernetes config found — IaC executor disabled")
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
                    container='iac-runner',
                    tail_lines=50000,
                )
            except k8s_client.ApiException:
                logger.debug(f"Could not fetch pod logs for {pod_name}, pod may already be deleted")
                return

            if log_text:
                await self.log_persistence.push_logs(
                    request_id=request_id,
                    job_type='terraform',
                    project_name=project_name,
                    log_text=log_text,
                )
        except Exception as e:
            logger.warning(f"Failed to persist logs for {request_id}: {e}")

    async def monitor_task_status(self, job_name, request_id, project_name, workspace_name, poll_interval=5, grace_period=60, timeout_hours=None):
        """Monitor a K8s Job until completion, failure, or timeout"""
        try:
            success, request_details = await self.request_tracker.get_request_details(request_id)
            if not success:
                error_msg = f"Failed to fetch initial request details: {request_details}"
                await self.request_tracker.update_error_details(request_id, error_msg)
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
                # Check if request already reached terminal state (updated by the job itself)
                success, updated = await self.request_tracker.get_request_details(request_id)
                if success:
                    state = updated.get("state")
                    if state in ["completed", "failed", "execution failed", "timed out", "cancelled"]:
                        logger.info(f"Request {request_id} reached terminal state: {state}")
                        await self._release_workspace_lock(project_name, workspace_name)
                        return

                # Check K8s job status
                try:
                    job = self.batch_v1.read_namespaced_job_status(name=job_name, namespace=self.namespace)
                    if job.status.succeeded and job.status.succeeded > 0:
                        await asyncio.sleep(grace_period)
                        success, final = await self.request_tracker.get_request_details(request_id)
                        if success and final.get("state") not in ["completed", "failed", "execution failed"]:
                            await self.request_tracker.update_request_state(request_id, "completed")
                        await self._release_workspace_lock(project_name, workspace_name)
                        return

                    if job.status.failed and job.status.failed > 0:
                        await asyncio.sleep(grace_period)
                        success, final = await self.request_tracker.get_request_details(request_id)
                        if success and final.get("state") not in ["completed", "failed", "execution failed"]:
                            await self.request_tracker.update_error_details(request_id, "Run failed")
                            await self.request_tracker.update_request_state(request_id, "execution failed")
                        await self._release_workspace_lock(project_name, workspace_name)
                        return

                    # Check pod status for fatal container states that the Job
                    # controller doesn't count as "failed" (e.g. ErrImagePull)
                    pod_error = await self._check_pod_fatal_state(job_name)
                    if pod_error:
                        logger.warning(f"Pod fatal state detected for {job_name}: {pod_error}")
                        await self.request_tracker.update_error_details(request_id, pod_error)
                        await self.request_tracker.update_request_state(request_id, "execution failed")
                        await self.stop_task(job_name, reason=pod_error)
                        await self._release_workspace_lock(project_name, workspace_name)
                        return

                except k8s_client.ApiException as e:
                    if e.status == 404:
                        # Job was deleted or cleaned up
                        await asyncio.sleep(grace_period)
                        success, final = await self.request_tracker.get_request_details(request_id)
                        if success and final.get("state") not in ["completed", "failed", "execution failed", "timed out", "cancelled"]:
                            await self.request_tracker.update_error_details(request_id, "Run was interrupted unexpectedly")
                            await self.request_tracker.update_request_state(request_id, "execution failed")
                        await self._release_workspace_lock(project_name, workspace_name)
                        return
                    else:
                        logger.warning(f"K8s API error monitoring job {job_name}: {e.status} {e.reason}")

                await asyncio.sleep(poll_interval)

            # Timeout reached
            logger.warning(f"Request {request_id} timed out after {timeout_hours} hours")
            await self.request_tracker.update_error_details(request_id, f"Job exceeded timeout of {timeout_hours} hours")
            await self.stop_task(job_name)
            await self.request_tracker.update_request_state(request_id, "timed out")
            await self._release_workspace_lock(project_name, workspace_name)

        except Exception as e:
            error_msg = f"Error monitoring job: {str(e)}"
            await self.request_tracker.update_error_details(request_id, error_msg)
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

    async def trigger_terraform_command(self, project_name, workspace_name, run_details, phases, request_id, timeout_hours=None):
        try:
            lock_success, lock_message = await self._check_and_set_workspace_lock(project_name, workspace_name)
            if not lock_success:
                error_msg = f"Cannot start terraform run: {lock_message}"
                await self.request_tracker.update_error_details(self.request_id, error_msg)
                await self.request_tracker.update_request_state(self.request_id, 'failed')
                return {'status': 'error', 'error': error_msg}

            await self.request_tracker.update_request_state(self.request_id, 'queued')

            github_repo = run_details['github_repo']['repo_url']
            github_token = run_details['github_repo'].get('token')
            tf_config_path = run_details['github_repo']['terraform_config_path']
            terraform_version = run_details['terraform_version']
            github_branch = run_details['github_repo'].get('branch')
            policy_governance_path = run_details['github_repo'].get('policy_governance_path')
            org_policy_repo = run_details.get('org_policy_repo')

            required_fields = {
                'project_name': project_name,
                'workspace_name': workspace_name,
                'request_id': request_id,
                'terraform_version': terraform_version,
                'github_repo': github_repo
            }

            for field, value in required_fields.items():
                if value is None:
                    error_msg = f"Required field '{field}' is missing"
                    await self.request_tracker.update_error_details(self.request_id, error_msg)
                    await self.request_tracker.update_request_state(self.request_id, 'failed')
                    return {'status': 'error', 'error': error_msg}

            await self.request_tracker.update_request_state(self.request_id, 'in progress')

            # Extract backend config
            backend_config = run_details['backend_config']['backend_statefile_path']
            backend_type = run_details.get('backend_type', os.environ.get('TF_BACKEND_TYPE', 'kubernetes')).lower()

            # IaC engine: tofu (default, open source) or terraform (enterprise swap)
            tf_engine = 'tofu'
            if self.config_manager:
                tf_engine = self.config_manager.get_config('terraform', 'engine') or 'tofu'

            # Build environment variables for the K8s Job
            env_vars = [
                {'name': 'PROJECT_NAME', 'value': project_name},
                {'name': 'TF_ENGINE', 'value': tf_engine},
                {'name': 'WORKSPACE_NAME', 'value': workspace_name},
                {'name': 'REQUEST_ID', 'value': request_id},
                {'name': 'QUBIVA_API_ENDPOINT', 'value': os.environ.get('QUBIVA_API_ENDPOINT', '')},
                {'name': 'TERRAFORM_VERSION', 'value': terraform_version},
                {'name': 'GITHUB_REPO', 'value': github_repo},
            ]

            if backend_config and backend_type not in ['s3', 'gcs']:
                env_vars.append({'name': 'TF_BACKEND_KEY', 'value': backend_config})

            if backend_type in ['s3', 'gcs']:
                if '/' not in backend_config:
                    error_msg = f"Invalid backend_statefile_path '{backend_config}' for backend type '{backend_type}'. Expected '<bucket>/<key>'."
                    await self.request_tracker.update_error_details(self.request_id, error_msg)
                    await self.request_tracker.update_request_state(self.request_id, 'failed')
                    return {'status': 'error', 'error': error_msg}

                bucket_name, *key_parts = backend_config.split('/')
                key = '/'.join(key_parts)
                env_vars.append({'name': 'TF_BACKEND_BUCKET', 'value': bucket_name})
                env_vars.append({'name': 'TF_BACKEND_KEY', 'value': key})

                if backend_type == 's3':
                    env_vars.append({'name': 'TF_STATE_LOCK_TABLE', 'value': os.environ.get('TF_STATE_LOCK_TABLE', '')})

            if github_branch:
                env_vars.append({'name': 'GITHUB_BRANCH', 'value': github_branch})
            if tf_config_path:
                env_vars.append({'name': 'TF_CONFIG_PATH', 'value': str(tf_config_path)})
            if github_token:
                encoded_token = urllib.parse.quote(github_token, safe='')
                env_vars.append({'name': 'GITHUB_TOKEN', 'value': encoded_token})

            for k, v in run_details['variables'].items():
                if v is not None:
                    env_vars.append({'name': f'TF_VAR_{k}', 'value': str(v)})
            for k, v in run_details['secrets'].items():
                if v is not None:
                    env_vars.append({'name': f'TF_VAR_{k}', 'value': str(v)})
            for k, v in run_details['auth_env_vars'].items():
                if v is not None:
                    env_vars.append({'name': k, 'value': str(v)})

            # Pass selected execution phases to runner
            if phases:
                env_vars.append({'name': 'TF_PHASES', 'value': ','.join(phases)})

            # Pass backend type (kubernetes, s3, local, gcs, azurerm)
            env_vars.append({'name': 'TF_BACKEND_TYPE', 'value': backend_type})

            if backend_type == 'kubernetes':
                env_vars.append({'name': 'TF_BACKEND_NAMESPACE', 'value': self.namespace})

            # Pass internal API key for authenticated callbacks
            internal_api_key = os.environ.get('INTERNAL_API_KEY')
            if internal_api_key:
                env_vars.append({'name': 'INTERNAL_API_KEY', 'value': internal_api_key})

            if policy_governance_path:
                env_vars.append({'name': 'REPO_POLICY_PATH', 'value': str(policy_governance_path)})

            if org_policy_repo:
                env_vars.append({'name': 'ORG_POLICY_REPO_URL', 'value': org_policy_repo['repo_url']})
                if org_policy_repo.get('branch'):
                    env_vars.append({'name': 'ORG_POLICY_BRANCH', 'value': org_policy_repo['branch']})
                if org_policy_repo.get('token'):
                    env_vars.append({'name': 'ORG_POLICY_TOKEN', 'value': org_policy_repo['token']})
                if org_policy_repo.get('policy_path'):
                    env_vars.append({'name': 'ORG_POLICY_PATH', 'value': org_policy_repo['policy_path']})
                if org_policy_repo.get('conftest_version'):
                    env_vars.append({'name': 'CONFTEST_VERSION', 'value': org_policy_repo['conftest_version']})

            # ── Pool-first execution path ─────────────────────────
            # If a runner pool is available, try to claim a pre-warmed pod
            # instead of creating a new K8s Job (saves 20-60s cold start).
            if self.pool_manager:
                pod = self.pool_manager.claim_pod(request_id, project_name=project_name)
                if pod:
                    inject_result = await self.pool_manager.inject_env_and_execute(pod, env_vars)
                    if not inject_result.get("error"):
                        await self.request_tracker.update_job_name(request_id, pod.pod_name)
                        success, message = await self.request_tracker.update_log_stream(
                            request_id, pod.pod_name, "iac-runner"
                        )
                        if not success:
                            logger.error(f"Failed to update log stream: {message}")

                        asyncio.create_task(
                            self.pool_manager.monitor_execution(
                                pod=pod,
                                request_id=request_id,
                                request_tracker=self.request_tracker,
                                project_name=project_name,
                                workspace_name=workspace_name,
                                log_persistence=self.log_persistence,
                                timeout_hours=timeout_hours or self.DEFAULT_TIMEOUT_HOURS,
                            )
                        )

                        logger.info(f"IaC execution started via pool pod: {pod.pod_name}")
                        return {
                            'status': 'success',
                            'task_arn': pod.pod_name,
                            'log_stream_name': f"{pod.pod_name}:iac-runner",
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

            # Create Kubernetes Job (fallback when pool is disabled or empty)
            job_name = f"iac-{request_id[:20].lower().replace('_', '-')}"
            k8s_env = [k8s_client.V1EnvVar(name=e['name'], value=e['value']) for e in env_vars]

            container = k8s_client.V1Container(
                name='iac-runner',
                image=self.job_image,
                image_pull_policy='IfNotPresent',
                env=k8s_env,
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
                        'component': 'iac-runner',
                        'request-id': request_id[:63],
                    }
                ),
                spec=k8s_client.V1JobSpec(
                    template=k8s_client.V1PodTemplateSpec(
                        metadata=k8s_client.V1ObjectMeta(
                            labels={
                                'app': 'qubiva',
                                'component': 'iac-runner',
                            }
                        ),
                        spec=k8s_client.V1PodSpec(
                            containers=[container],
                            restart_policy='Never',
                            service_account_name=os.environ.get('RUNNER_SERVICE_ACCOUNT', 'qubiva-runner'),
                        )
                    ),
                    backoff_limit=0,
                    ttl_seconds_after_finished=self.job_ttl_seconds,
                )
            )

            self.batch_v1.create_namespaced_job(namespace=self.namespace, body=job)
            logger.info(f"IaC K8s job created: {job_name}")

            # Store job name in request for stop/cancel support
            await self.request_tracker.update_job_name(request_id, job_name)

            # Get pod name for log streaming
            await asyncio.sleep(2)
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f'job-name={job_name}'
            )
            pod_name = pods.items[0].metadata.name if pods.items else job_name

            # Update log stream reference
            log_ref = f"{pod_name}:iac-runner"
            success, message = await self.request_tracker.update_log_stream(request_id, pod_name, "iac-runner")
            if not success:
                logger.error(f"Failed to update log stream: {message}")

            # Start monitoring
            asyncio.create_task(self.monitor_task_status(job_name, request_id, project_name, workspace_name, timeout_hours=timeout_hours))

            return {
                'status': 'success',
                'task_arn': job_name,
                'log_stream_name': log_ref
            }

        except Exception as e:
            error_msg = f"Unexpected error during IaC execution: {str(e)}"
            await self.request_tracker.update_error_details(self.request_id, error_msg)
            await self.request_tracker.update_request_state(self.request_id, 'failed')
            await self._release_workspace_lock(project_name, workspace_name)
            logger.error(f"Error in trigger_iac_command: {str(e)}")
            logger.error(traceback.format_exc())
            return {'status': 'error', 'error': error_msg}

    async def _check_and_set_workspace_lock(self, project_name, workspace_name):
        try:
            is_locked, current_run_id = await self.project_manager.is_workspace_locked(project_name, workspace_name)

            if is_locked and current_run_id:
                success, run_details = await self.request_tracker.get_request_details(current_run_id)
                if success and run_details.get('state') in ['in progress', 'queued']:
                    return False, f"Workspace is locked by active request {current_run_id}"
                else:
                    logger.info(f"Clearing stale lock from request {current_run_id}")
                    await self.project_manager.set_workspace_state(project_name, workspace_name, False)

            success, message = await self.project_manager.set_workspace_state(
                project_name, workspace_name, True, self.request_id
            )

            if success:
                logger.info(f"Workspace {project_name}/{workspace_name} locked by request {self.request_id}")
                return True, "Workspace locked successfully"
            else:
                return False, f"Failed to lock workspace: {message}"

        except Exception as e:
            return False, f"Error checking workspace lock: {str(e)}"

    async def _release_workspace_lock(self, project_name, workspace_name):
        try:
            success, message = await self.project_manager.set_workspace_state(
                project_name, workspace_name, False
            )
            if success:
                logger.info(f"Workspace {project_name}/{workspace_name} unlocked")
            else:
                logger.error(f"Failed to unlock workspace: {message}")
            return success, message
        except Exception as e:
            logger.error(f"Error releasing workspace lock: {str(e)}")
            return False, f"Error releasing workspace lock: {str(e)}"
