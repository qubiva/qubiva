"""Runner pool manager — pre-warmed pod pools for IaC and discovery batch runners.

Instead of creating a new K8s Job for every request (cold start: image pull + init),
pool pods are created in advance with POOL_MODE=true. They run an entrypoint that
installs tooling (terraform versions, query engine/compliance engine) and then wait for a
signal file (/tmp/start_execution) before sourcing /tmp/job_env.sh and executing.

This eliminates the 30-60s cold start for each batch run.

Flow:
1. App startup: create N pool pods per runner type (configurable)
2. Request arrives: claim a READY pod, inject env vars via kubectl exec, touch signal file
3. Monitor execution (request_tracker + pod phase) until terminal state
4. Persist logs, release locks, delete pod, replenish pool
"""
import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Dict, List, Optional

from kubernetes import client as k8s_client, config as k8s_config

logger = logging.getLogger('uvicorn.error')


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RunnerType(str, Enum):
    IAC = "iac"
    DISCOVERY = "discovery"


class PoolPodStatus(str, Enum):
    STARTING = "starting"
    READY = "ready"
    CLAIMED = "claimed"
    EXECUTING = "executing"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PoolPod:
    """Tracks a single pod in the runner pool."""
    pod_name: str
    namespace: str
    runner_type: RunnerType
    status: PoolPodStatus = PoolPodStatus.STARTING
    created_at: float = field(default_factory=time.time)
    claimed_at: Optional[float] = None
    request_id: Optional[str] = None
    project_name: Optional[str] = None
    container_name: str = ""


# ---------------------------------------------------------------------------
# Terminal request states (used by monitor_execution)
# ---------------------------------------------------------------------------

TERMINAL_STATES = frozenset({
    "completed",
    "failed",
    "execution failed",
    "timed out",
    "cancelled",
    "benchmark succeeded",
    "benchmark failed",
})


# ---------------------------------------------------------------------------
# RunnerPoolManager
# ---------------------------------------------------------------------------

class RunnerPoolManager:
    """Manages a pool of pre-warmed pods for a specific runner type.

    One instance per runner type (iac, discovery). Created at app startup
    and shared across all request handlers.

    Args:
        runner_type: Which runner this pool manages.
        config_manager: The ConfigManager class (singleton pattern — call
            config_manager.get_config(...) directly on the class).
        tf_versions: Optional TerraformVersionManager instance. Required for
            IAC runner type to pass supported versions to pool pods.
    """

    # Class-level registry of all pool manager instances (for cross-pool quota checks)
    _all_managers: ClassVar[List["RunnerPoolManager"]] = []

    def __init__(self, runner_type: RunnerType, config_manager, tf_versions=None):
        self.runner_type = runner_type
        self.config_manager = config_manager
        self.tf_versions = tf_versions
        self.namespace = os.environ.get('K8S_NAMESPACE', 'default')

        # Runner-specific configuration
        if runner_type == RunnerType.IAC:
            self.runner_image = os.environ.get(
                'IAC_RUNNER_IMAGE', 'qubiva/iac-runner:latest'
            )
            self.container_name = 'iac-runner'
            self.pod_prefix = 'iac-pool'
            self.component_label = 'iac-runner'
            self.managed_by_label = 'qubiva-iac-pool'
        else:
            self.runner_image = os.environ.get(
                'DISCOVERY_RUNNER_IMAGE', 'qubiva/discovery-runner:latest'
            )
            self.container_name = 'discovery-runner'
            self.pod_prefix = 'sp-pool'
            self.component_label = 'discovery-runner'
            self.managed_by_label = 'qubiva-discovery-pool'

        # Internal state
        self._pool: Dict[str, PoolPod] = {}       # pod_name -> PoolPod (STARTING/READY)
        self._active: Dict[str, PoolPod] = {}      # pod_name -> PoolPod (CLAIMED/EXECUTING)
        self._replenish_lock = asyncio.Lock()

        self._init_k8s_client()

        # Register this instance for cross-pool quota checks
        RunnerPoolManager._all_managers.append(self)

    def _init_k8s_client(self):
        """Initialize Kubernetes client (in-cluster first, fallback to kubeconfig)."""
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
            self.core_v1 = k8s_client.CoreV1Api(api_client=api_client)
        except k8s_config.ConfigException:
            logger.warning(
                "No Kubernetes config found — %s runner pool disabled",
                self.runner_type.value,
            )
            self.core_v1 = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _get_pool_config(self) -> dict:
        """Read pool config from app_config.json -> runner_pools -> {runner_type}.

        Expected config shape:
            {
                "runner_pools": {
                    "iac": {
                        "enabled": true,
                        "pool_size": 2,
                        "pod_timeout_seconds": 3600
                    },
                    "discovery": {
                        "enabled": true,
                        "pool_size": 1,
                        "pod_timeout_seconds": 3600
                    }
                }
            }
        """
        pools_config = self.config_manager.get_config("runner_pools") or {}
        return pools_config.get(self.runner_type.value, {})

    def get_pool_size(self) -> int:
        """Return target pool size. Returns 0 if pool is disabled."""
        config = self._get_pool_config()
        if not config.get("enabled", False):
            return 0
        return config.get("pool_size", 0)

    def get_execution_mode(self) -> str:
        """Return execution mode: 'pool_with_fallback' (default) or 'pool_only'."""
        config = self._get_pool_config()
        return config.get("execution_mode", "pool_with_fallback")

    # ------------------------------------------------------------------
    # Per-project quotas
    # ------------------------------------------------------------------

    def _get_project_quota(self) -> int:
        """Return max concurrent pool runners allowed per project (0 = unlimited)."""
        pools_config = self.config_manager.get_config("runner_pools") or {}
        quotas = pools_config.get("quotas", {})
        return quotas.get("max_concurrent_per_project", 0)

    @classmethod
    def count_active_for_project(cls, project_name: str) -> int:
        """Count active pool runners for a project across all pool managers."""
        return sum(
            1 for mgr in cls._all_managers
            for pod in mgr._active.values()
            if pod.project_name == project_name
        )

    @classmethod
    def get_pool_summary(cls) -> dict:
        """Return a summary of all runner pools for dashboard display."""
        summary = {}
        for mgr in cls._all_managers:
            pool_size = mgr.get_pool_size()
            ready = sum(1 for p in mgr._pool.values() if p.status == PoolPodStatus.READY)
            starting = sum(1 for p in mgr._pool.values() if p.status == PoolPodStatus.STARTING)
            busy = len(mgr._active)
            summary[mgr.runner_type.value] = {
                "enabled": pool_size > 0,
                "target_size": pool_size,
                "ready": ready,
                "starting": starting,
                "busy": busy,
                "execution_mode": mgr.get_execution_mode(),
            }
        return summary

    # ------------------------------------------------------------------
    # Config change handling
    # ------------------------------------------------------------------

    async def on_config_change(self, changed_keys: list):
        """React to config changes detected by ConfigManager.

        If runner_pools config changed, adjust the pool size dynamically:
        - Pool size increased: replenish adds more pods
        - Pool size decreased: drain excess idle READY pods
        - Pool disabled: drain all idle pods
        """
        if "runner_pools" not in changed_keys:
            return

        new_size = self.get_pool_size()
        idle = len(self._pool)
        active = len(self._active)
        total = idle + active

        logger.info(
            "%s pool config changed — target size: %d, current: %d idle + %d active",
            self.runner_type.value, new_size, idle, active,
        )

        if new_size <= 0:
            # Pool disabled — drain all idle pods
            for pod_name in list(self._pool.keys()):
                pod = self._pool.pop(pod_name, None)
                if pod:
                    self._delete_pod(pod_name)
                    logger.info("Drained %s pool pod (pool disabled): %s",
                                self.runner_type.value, pod_name)
            return

        if total > new_size:
            # Pool shrunk — remove excess idle READY pods (oldest first)
            excess = total - new_size
            pods_by_age = sorted(
                self._pool.items(),
                key=lambda kv: kv[1].created_at,
            )
            removed = 0
            for pod_name, pool_pod in pods_by_age:
                if removed >= excess:
                    break
                if pool_pod.status == PoolPodStatus.READY:
                    self._pool.pop(pod_name, None)
                    self._delete_pod(pod_name)
                    removed += 1
                    logger.info("Drained excess %s pool pod: %s",
                                self.runner_type.value, pod_name)

        # Replenish if we need more
        await self._replenish_pool()

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    async def start_pool(self):
        """Initialize the pool on app startup.

        Cleans up orphaned pods from previous runs, then creates pods up to
        the configured pool_size.
        """
        if self.core_v1 is None:
            logger.info(
                "%s runner pool skipped (no K8s client)",
                self.runner_type.value,
            )
            return

        pool_size = self.get_pool_size()
        if pool_size <= 0:
            logger.info(
                "%s runner pool disabled (pool_size=0 or not enabled)",
                self.runner_type.value,
            )
            return

        logger.info(
            "Initializing %s runner pool (target size: %d)",
            self.runner_type.value, pool_size,
        )

        await self._cleanup_orphaned_pool_pods()
        await self._replenish_pool()

    async def cleanup_all(self):
        """Delete all idle pool pods (NOT active/executing ones). Called on shutdown."""
        for pod_name in list(self._pool.keys()):
            pod = self._pool.pop(pod_name, None)
            if pod:
                self._delete_pod(pod_name)
                logger.info("Cleaned up pool pod on shutdown: %s", pod_name)

    # ------------------------------------------------------------------
    # Pool replenishment
    # ------------------------------------------------------------------

    async def _replenish_pool(self):
        """Create pods until total (idle + active) reaches target size.

        pool_size is total capacity — busy pods count towards it, so
        claiming a pod does NOT create a replacement beyond the target.
        """
        pool_size = self.get_pool_size()
        if pool_size <= 0:
            return

        async with self._replenish_lock:
            idle = len(self._pool)
            active = len(self._active)
            needed = pool_size - (idle + active)
            if needed <= 0:
                return

            logger.info(
                "Replenishing %s pool: %d idle + %d active = %d/%d (creating %d)",
                self.runner_type.value, idle, active, idle + active, pool_size, needed,
            )
            for _ in range(needed):
                await self._create_pool_pod()

    async def _create_pool_pod(self):
        """Create a single pre-warmed pool pod."""
        pool_id = uuid.uuid4().hex[:10]
        pod_name = f"{self.pod_prefix}-{pool_id}"

        try:
            env_vars = self._build_pool_env_vars()
            pod_spec = self._build_pool_pod_spec(pod_name, env_vars)

            self.core_v1.create_namespaced_pod(
                namespace=self.namespace, body=pod_spec
            )
            logger.info("Created %s pool pod: %s", self.runner_type.value, pod_name)

            pool_pod = PoolPod(
                pod_name=pod_name,
                namespace=self.namespace,
                runner_type=self.runner_type,
                status=PoolPodStatus.STARTING,
                container_name=self.container_name,
            )
            self._pool[pod_name] = pool_pod

            # Wait for readiness in background
            asyncio.create_task(self._wait_for_pod_ready(pod_name))

        except Exception as e:
            logger.error(
                "Failed to create %s pool pod %s: %s",
                self.runner_type.value, pod_name, e,
            )

    def _build_pool_env_vars(self) -> List[k8s_client.V1EnvVar]:
        """Build K8s env vars for a pool pod.

        All pool pods get POOL_MODE=true so the runner entrypoint knows to
        wait for /tmp/start_execution instead of running immediately.
        """
        env_vars = [
            k8s_client.V1EnvVar(name="POOL_MODE", value="true"),
        ]

        if self.runner_type == RunnerType.IAC:
            # IaC engine version is workspace-specific — downloaded on-demand.
            # Only pass the engine type so the pod knows which binary to download.
            tf_engine = self.config_manager.get_config("terraform", "engine") or "tofu"
            env_vars.append(k8s_client.V1EnvVar(name="TF_ENGINE", value=tf_engine))

        elif self.runner_type == RunnerType.DISCOVERY:
            # Pass query engine/compliance engine versions from app config
            versions_config = self.config_manager.get_config("query_engine_versions") or {}
            qe_version = versions_config.get("query_engine_version", "latest")
            ce_version = versions_config.get("compliance_engine_version", "latest")

            env_vars.append(k8s_client.V1EnvVar(
                name="QUERY_ENGINE_VERSION", value=qe_version,
            ))
            env_vars.append(k8s_client.V1EnvVar(
                name="COMPLIANCE_ENGINE_VERSION", value=ce_version,
            ))

        return env_vars

    # ------------------------------------------------------------------
    # Pod spec builder
    # ------------------------------------------------------------------

    def _build_pool_pod_spec(
        self,
        pod_name: str,
        env_vars: List[k8s_client.V1EnvVar],
    ) -> k8s_client.V1Pod:
        """Build the K8s Pod manifest for a pre-warmed pool pod."""

        # Runner-specific command
        if self.runner_type == RunnerType.IAC:
            command = ["/bin/bash", "-c", "source /usr/local/bin/runner.sh"]
        else:
            command = ["/bin/bash", "-c", "source /home/runner/runner.sh"]

        # Volume mounts (discovery runner needs artifacts PVC)
        volume_mounts = []
        volumes = []
        if self.runner_type == RunnerType.DISCOVERY:
            artifacts_path = os.environ.get(
                'ARTIFACTS_STORAGE_PATH', '/app/data/artifacts'
            )
            volume_mounts.append(k8s_client.V1VolumeMount(
                name='artifacts-storage',
                mount_path=artifacts_path,
            ))
            volumes.append(k8s_client.V1Volume(
                name='artifacts-storage',
                persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                    claim_name='qubiva-artifacts',
                ),
            ))

        container = k8s_client.V1Container(
            name=self.container_name,
            image=self.runner_image,
            image_pull_policy='IfNotPresent',
            command=command,
            env=env_vars,
            volume_mounts=volume_mounts or None,
            resources=k8s_client.V1ResourceRequirements(
                requests={'memory': '512Mi', 'cpu': '250m'},
                limits={'memory': '2Gi', 'cpu': '1'},
            ),
            readiness_probe=k8s_client.V1Probe(
                _exec=k8s_client.V1ExecAction(
                    command=["test", "-f", "/tmp/pool_ready"],
                ),
                initial_delay_seconds=5,
                period_seconds=5,
                failure_threshold=60,  # Up to 5min total startup time
            ),
        )

        labels = {
            'app': 'qubiva',
            'component': self.component_label,
            'managed-by': self.managed_by_label,
            'pool': 'true',
        }

        return k8s_client.V1Pod(
            api_version='v1',
            kind='Pod',
            metadata=k8s_client.V1ObjectMeta(
                name=pod_name,
                namespace=self.namespace,
                labels=labels,
            ),
            spec=k8s_client.V1PodSpec(
                containers=[container],
                volumes=volumes or None,
                restart_policy='Never',
                service_account_name=os.environ.get(
                    'RUNNER_SERVICE_ACCOUNT', 'qubiva-runner'
                ),
                active_deadline_seconds=3600,  # Safety kill: 1 hour
            ),
        )

    # ------------------------------------------------------------------
    # Pod readiness
    # ------------------------------------------------------------------

    async def _wait_for_pod_ready(self, pod_name: str, timeout: int | None = None):
        """Poll K8s pod status until the readiness probe passes or timeout."""
        if timeout is None:
            pool_config = self._get_pool_config()
            timeout = pool_config.get("stale_threshold_seconds", 600)
        pool_pod = self._pool.get(pod_name)
        if not pool_pod:
            return

        start = time.time()
        while time.time() - start < timeout:
            try:
                pod = self.core_v1.read_namespaced_pod_status(
                    name=pod_name, namespace=self.namespace
                )

                if pod.status.phase in ("Failed", "Unknown"):
                    logger.warning(
                        "%s pool pod %s entered %s phase",
                        self.runner_type.value, pod_name, pod.status.phase,
                    )
                    self._pool.pop(pod_name, None)
                    return

                if pod.status.container_statuses:
                    cs = pod.status.container_statuses[0]
                    if cs.ready:
                        pool_pod.status = PoolPodStatus.READY
                        logger.info(
                            "%s pool pod %s is READY",
                            self.runner_type.value, pod_name,
                        )
                        return

                    # Check for fatal container states
                    if cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason or ""
                        fatal = {
                            "ErrImagePull", "ImagePullBackOff",
                            "InvalidImageName", "CrashLoopBackOff",
                            "CreateContainerConfigError",
                        }
                        if reason in fatal:
                            logger.warning(
                                "%s pool pod %s fatal: %s",
                                self.runner_type.value, pod_name, reason,
                            )
                            self._pool.pop(pod_name, None)
                            self._delete_pod(pod_name)
                            return

            except k8s_client.ApiException as e:
                if e.status == 404:
                    self._pool.pop(pod_name, None)
                    return

            await asyncio.sleep(3)

        # Timeout
        logger.warning(
            "%s pool pod %s timed out waiting for ready (%ds)",
            self.runner_type.value, pod_name, timeout,
        )
        self._pool.pop(pod_name, None)
        self._delete_pod(pod_name)

    # ------------------------------------------------------------------
    # Claim a pod
    # ------------------------------------------------------------------

    def claim_pod(self, request_id: str, project_name: str = None) -> Optional[PoolPod]:
        """Synchronously claim the first READY pod from the pool.

        Returns a PoolPod if one is available, None otherwise. The caller
        should then use inject_env_and_execute() to start the actual work.

        Args:
            request_id: Unique request identifier.
            project_name: Project requesting the runner (used for quota checks).

        Triggers background replenishment after claiming.
        """
        # Per-project concurrency quota check (across all pool managers)
        if project_name:
            quota = self._get_project_quota()
            if quota > 0:
                active_count = RunnerPoolManager.count_active_for_project(project_name)
                if active_count >= quota:
                    logger.info(
                        "Project %s at runner quota limit (%d/%d), falling back to Job",
                        project_name, active_count, quota,
                    )
                    return None

        for pod_name, pool_pod in list(self._pool.items()):
            if pool_pod.status == PoolPodStatus.READY:
                # Move from pool to active
                self._pool.pop(pod_name)
                pool_pod.status = PoolPodStatus.CLAIMED
                pool_pod.claimed_at = time.time()
                pool_pod.request_id = request_id
                pool_pod.project_name = project_name
                self._active[pod_name] = pool_pod

                logger.info(
                    "Claimed %s pool pod %s for request %s (project: %s)",
                    self.runner_type.value, pod_name, request_id, project_name,
                )

                # Replenish in background
                asyncio.create_task(self._replenish_pool())
                return pool_pod

        return None

    # ------------------------------------------------------------------
    # Env injection and execution
    # ------------------------------------------------------------------

    async def inject_env_and_execute(
        self,
        pod: PoolPod,
        env_vars: List[dict],
    ):
        """Write env vars into the pod and trigger execution.

        1. Writes each env var to /tmp/job_env.sh as shell exports
        2. Touches /tmp/start_execution to signal the runner entrypoint

        Args:
            pod: The claimed PoolPod.
            env_vars: List of dicts with 'name' and 'value' keys.
        """
        pod.status = PoolPodStatus.EXECUTING

        # Build the env file content with proper shell escaping
        lines = ["#!/bin/bash", "# Injected by runner pool manager"]
        for ev in env_vars:
            name = ev['name']
            value = ev.get('value', '')
            # Shell-escape: wrap in single quotes, escape internal single quotes
            escaped_value = value.replace("'", "'\\''")
            lines.append(f"export {name}='{escaped_value}'")

        env_script = "\n".join(lines) + "\n"

        # Write env file
        write_cmd = (
            f"cat > /tmp/job_env.sh << 'ENVEOF'\n{env_script}ENVEOF\n"
            f"chmod +x /tmp/job_env.sh"
        )
        result = await self._exec_in_pod(
            pod.pod_name,
            ["/bin/bash", "-c", write_cmd],
            timeout=15,
        )
        if result.get("error"):
            logger.error(
                "Failed to inject env vars into %s: %s",
                pod.pod_name, result["error"],
            )
            return result

        # Touch the signal file to start execution
        result = await self._exec_in_pod(
            pod.pod_name,
            ["/bin/bash", "-c", "touch /tmp/start_execution"],
            timeout=10,
        )
        if result.get("error"):
            logger.error(
                "Failed to signal execution start in %s: %s",
                pod.pod_name, result["error"],
            )
            return result

        logger.info(
            "Injected %d env vars and triggered execution in %s pool pod %s",
            len(env_vars), self.runner_type.value, pod.pod_name,
        )
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Execution monitoring
    # ------------------------------------------------------------------

    async def monitor_execution(
        self,
        pod: PoolPod,
        request_id: str,
        request_tracker,
        project_name: str,
        workspace_name: Optional[str] = None,
        log_persistence=None,
        poll_interval: int = 5,
        timeout_hours: int = 6,
    ):
        """Monitor a running pool pod until the request reaches a terminal state.

        Primary signal: request_tracker state (updated by the runner via HTTP callback).
        Secondary signal: K8s pod phase (Succeeded/Failed) and container exit codes.

        After completion (or timeout):
        1. Persist logs from the pod
        2. Release workspace lock (terraform only)
        3. Delete the pod
        4. Remove from _active tracking dict

        This should be run as a background asyncio.Task.
        """
        grace_period_seconds = 30
        timeout_seconds = timeout_hours * 3600
        start_time = time.time()

        try:
            while (time.time() - start_time) < timeout_seconds:
                # ── Primary: check request state ──────────────────────
                success, details = await request_tracker.get_request_details(request_id)
                if success:
                    state = details.get("state")
                    if state in TERMINAL_STATES:
                        logger.info(
                            "Request %s reached terminal state: %s (pod %s)",
                            request_id, state, pod.pod_name,
                        )
                        pod.status = PoolPodStatus.COMPLETED
                        return

                # ── Secondary: check pod phase ────────────────────────
                try:
                    k8s_pod = self.core_v1.read_namespaced_pod_status(
                        name=pod.pod_name, namespace=self.namespace
                    )
                    pod_phase = k8s_pod.status.phase

                    if pod_phase in ("Succeeded", "Failed"):
                        # Pod terminated — give the runner a grace period to
                        # make its final callback before we check state
                        logger.info(
                            "Pod %s terminated (phase=%s), grace period %ds",
                            pod.pod_name, pod_phase, grace_period_seconds,
                        )
                        await asyncio.sleep(grace_period_seconds)

                        # Re-check request state after grace period
                        success, details = await request_tracker.get_request_details(request_id)
                        if success:
                            state = details.get("state")
                            if state in TERMINAL_STATES:
                                pod.status = PoolPodStatus.COMPLETED
                                return

                        # Runner didn't update state — determine outcome from exit code
                        exit_code = self._get_container_exit_code(k8s_pod)
                        if pod_phase == "Succeeded" or exit_code == 0:
                            await request_tracker.update_request_state(
                                request_id, "completed"
                            )
                        else:
                            await request_tracker.update_error_details(
                                request_id,
                                f"Runner pod exited with code {exit_code}",
                            )
                            await request_tracker.update_request_state(
                                request_id, "execution failed"
                            )
                        pod.status = PoolPodStatus.COMPLETED
                        return

                except k8s_client.ApiException as e:
                    if e.status == 404:
                        # Pod was deleted externally
                        await asyncio.sleep(grace_period_seconds)
                        success, details = await request_tracker.get_request_details(request_id)
                        if success:
                            state = details.get("state")
                            if state not in TERMINAL_STATES:
                                await request_tracker.update_error_details(
                                    request_id,
                                    "Runner pod was deleted unexpectedly",
                                )
                                await request_tracker.update_request_state(
                                    request_id, "execution failed"
                                )
                        pod.status = PoolPodStatus.COMPLETED
                        return
                    else:
                        logger.warning(
                            "K8s API error monitoring pod %s: %s %s",
                            pod.pod_name, e.status, e.reason,
                        )

                await asyncio.sleep(poll_interval)

            # ── Timeout ───────────────────────────────────────────────
            logger.warning(
                "Request %s timed out after %d hours (pod %s)",
                request_id, timeout_hours, pod.pod_name,
            )
            await request_tracker.update_error_details(
                request_id,
                f"Runner exceeded timeout of {timeout_hours} hours",
            )
            await request_tracker.update_request_state(request_id, "timed out")
            pod.status = PoolPodStatus.COMPLETED

        except Exception as e:
            logger.error(
                "Error monitoring pool pod %s for request %s: %s",
                pod.pod_name, request_id, e,
            )
            await request_tracker.update_error_details(
                request_id, f"Monitoring error: {e}"
            )

        finally:
            # Always: persist logs, release lock, clean up
            await self._persist_pod_logs(
                pod.pod_name, request_id, project_name, log_persistence
            )

            if self.runner_type == RunnerType.IAC and workspace_name:
                await self._release_workspace_lock(
                    request_tracker, project_name, workspace_name
                )

            self._active.pop(pod.pod_name, None)
            self._delete_pod(pod.pod_name)

    def _get_container_exit_code(self, k8s_pod) -> Optional[int]:
        """Extract the container exit code from a terminated pod."""
        try:
            if k8s_pod.status.container_statuses:
                for cs in k8s_pod.status.container_statuses:
                    if cs.name == self.container_name and cs.state and cs.state.terminated:
                        return cs.state.terminated.exit_code
        except Exception:
            pass
        return None

    async def _release_workspace_lock(
        self, request_tracker, project_name: str, workspace_name: str
    ):
        """Release terraform workspace lock. Requires project_manager from request_tracker."""
        try:
            # The project_manager is needed for workspace lock release.
            # We access it through a well-known import rather than threading it through.
            from app.deps import project_manager
            success, message = await project_manager.set_workspace_state(
                project_name, workspace_name, False
            )
            if success:
                logger.info("Workspace %s/%s unlocked", project_name, workspace_name)
            else:
                logger.error("Failed to unlock workspace: %s", message)
        except Exception as e:
            logger.error("Error releasing workspace lock: %s", e)

    # ------------------------------------------------------------------
    # Log persistence for pool pods
    # ------------------------------------------------------------------

    async def _persist_pod_logs(
        self,
        pod_name: str,
        request_id: str,
        project_name: str,
        log_persistence=None,
    ):
        """Read pod logs directly and push to Loki for long-term storage.

        Unlike K8s Job pods, pool pods are standalone — we cannot use
        label_selector=job-name=... to find them. Instead we read logs
        directly by pod name.
        """
        if not log_persistence:
            return

        try:
            log_text = self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                container=self.container_name,
                tail_lines=50000,
            )
        except k8s_client.ApiException:
            logger.debug(
                "Could not fetch logs for pool pod %s, pod may already be deleted",
                pod_name,
            )
            return
        except Exception as e:
            logger.warning("Failed to read logs from pod %s: %s", pod_name, e)
            return

        if log_text:
            try:
                await log_persistence.push_logs(
                    request_id=request_id,
                    job_type=self.runner_type.value,
                    project_name=project_name,
                    log_text=log_text,
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist logs for request %s: %s", request_id, e
                )

    # ------------------------------------------------------------------
    # Pool maintenance
    # ------------------------------------------------------------------

    async def pool_maintenance_loop(self):
        """Periodic maintenance: clean stale pods, remove expired idle pods, replenish.

        Should be called from a background task every ~30 seconds.
        """
        pool_size = self.get_pool_size()
        if pool_size <= 0:
            return

        pool_config = self._get_pool_config()
        pod_timeout = pool_config.get("pod_timeout_seconds", 3600)
        now = time.time()

        # Remove pods stuck in STARTING state for too long
        stale_timeout = pool_config.get("stale_threshold_seconds", 600)
        stale_threshold = now - stale_timeout
        for pod_name, pool_pod in list(self._pool.items()):
            if pool_pod.status == PoolPodStatus.STARTING and pool_pod.created_at < stale_threshold:
                logger.warning(
                    "Removing stale %s pool pod (stuck starting): %s",
                    self.runner_type.value, pod_name,
                )
                self._pool.pop(pod_name, None)
                self._delete_pod(pod_name)

        # Remove idle READY pods that have exceeded their timeout
        expiry_threshold = now - pod_timeout
        for pod_name, pool_pod in list(self._pool.items()):
            if pool_pod.status == PoolPodStatus.READY and pool_pod.created_at < expiry_threshold:
                logger.info(
                    "Removing expired idle %s pool pod: %s (age: %ds)",
                    self.runner_type.value, pod_name,
                    int(now - pool_pod.created_at),
                )
                self._pool.pop(pod_name, None)
                self._delete_pod(pod_name)

        # Replenish
        await self._replenish_pool()

    # ------------------------------------------------------------------
    # Orphan cleanup
    # ------------------------------------------------------------------

    async def _cleanup_orphaned_pool_pods(self):
        """Delete pool pods left over from a previous app instance.

        Uses the managed-by label to find only our pool's pods.
        """
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"managed-by={self.managed_by_label},pool=true",
            )
            for pod in pods.items:
                try:
                    self.core_v1.delete_namespaced_pod(
                        name=pod.metadata.name,
                        namespace=self.namespace,
                        grace_period_seconds=0,
                    )
                    logger.info(
                        "Cleaned up orphaned %s pool pod: %s",
                        self.runner_type.value, pod.metadata.name,
                    )
                except k8s_client.ApiException:
                    pass
        except Exception as e:
            logger.warning(
                "Failed to clean up orphaned %s pool pods: %s",
                self.runner_type.value, e,
            )

    # ------------------------------------------------------------------
    # Exec in pod
    # ------------------------------------------------------------------

    async def _exec_in_pod(
        self,
        pod_name: str,
        command: List[str],
        timeout: int = 30,
    ) -> dict:
        """Execute a command in a pod via K8s exec (stream API).

        Args:
            pod_name: Target pod name.
            command: Command and args as a list.
            timeout: Timeout in seconds.

        Returns:
            Dict with 'output' on success, 'error' on failure.
        """
        try:
            from kubernetes.stream import stream as k8s_stream

            def _exec():
                return k8s_stream(
                    self.core_v1.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    container=self.container_name,
                    command=command,
                    stderr=True,
                    stdout=True,
                    stdin=False,
                    tty=False,
                )

            output = await asyncio.wait_for(
                asyncio.to_thread(_exec),
                timeout=timeout,
            )
            return {"output": output}

        except asyncio.TimeoutError:
            return {"error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"error": f"Exec failed: {e}"}

    # ------------------------------------------------------------------
    # Pod deletion
    # ------------------------------------------------------------------

    def _delete_pod(self, pod_name: str):
        """Delete a pod with 0 grace period. Best-effort, swallows errors."""
        try:
            self.core_v1.delete_namespaced_pod(
                name=pod_name,
                namespace=self.namespace,
                grace_period_seconds=0,
            )
            logger.debug("Deleted pod: %s", pod_name)
        except k8s_client.ApiException as e:
            if e.status != 404:
                logger.warning("Error deleting pod %s: %s", pod_name, e.reason)
        except Exception as e:
            logger.warning("Error deleting pod %s: %s", pod_name, e)

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    def get_pool_status(self) -> dict:
        """Return a summary of pool state for health/debug endpoints."""
        pool_by_status = {}
        for pod in self._pool.values():
            status = pod.status.value
            pool_by_status[status] = pool_by_status.get(status, 0) + 1

        active_by_status = {}
        for pod in self._active.values():
            status = pod.status.value
            active_by_status[status] = active_by_status.get(status, 0) + 1

        return {
            "runner_type": self.runner_type.value,
            "target_size": self.get_pool_size(),
            "pool_pods": pool_by_status,
            "pool_total": len(self._pool),
            "active_pods": active_by_status,
            "active_total": len(self._active),
        }
