"""Cloud query session pod manager — creates and manages per-chat query pods.

Each chat conversation gets its own query pod with cloud credentials configured.
Pods are created on conversation start and destroyed on close or idle timeout.
Queries are executed via asyncpg connecting to the query engine's PostgreSQL wire protocol.
"""
import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import asyncpg
from kubernetes import client as k8s_client, config as k8s_config

from app.auth.cloud_auth import MultiCloudAuthentication

logger = logging.getLogger('uvicorn.error')


@dataclass
class QueryResult:
    """Result of a cloud SQL query."""
    columns: List[str]
    rows: List[dict]
    row_count: int
    truncated: bool = False
    error: Optional[str] = None


@dataclass
class SessionPod:
    """Tracks a running query session pod."""
    conversation_id: str
    pod_name: str
    namespace: str
    cloud_platform: Optional[str] = None  # may be None for org/project scope (multi-platform)
    status: str = "starting"  # starting, ready, error, terminated
    pod_ip: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    user: Optional[str] = None
    connected_accounts: Dict[str, str] = field(default_factory=dict)  # account_id -> platform


class QuerySessionManager:
    """Manages per-chat-session cloud query pods."""

    QUERY_ENGINE_PG_PORT = 9193
    QUERY_ENGINE_PG_USER = "steampipe"
    QUERY_ENGINE_PG_PASSWORD = "steampipe"
    QUERY_ENGINE_PG_DATABASE = "steampipe"

    def __init__(self, project_manager, config_manager):
        self.project_manager = project_manager
        self.config_manager = config_manager
        self.namespace = os.environ.get('K8S_NAMESPACE', 'default')
        self.runner_image = os.environ.get(
            'DISCOVERY_RUNNER_IMAGE', 'qubiva/discovery-runner:latest'
        )
        self._sessions: Dict[str, SessionPod] = {}
        self._connections: Dict[str, asyncpg.Connection] = {}
        # Pool: pre-warmed pods ready to be claimed by conversations
        self._pool: Dict[str, SessionPod] = {}  # pod_name -> SessionPod
        self._pool_replenish_lock = asyncio.Lock()
        self._init_k8s_client()

    def _init_k8s_client(self):
        """Initialize Kubernetes client (in-cluster or local kubeconfig)."""
        try:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            self.core_v1 = k8s_client.CoreV1Api()
        except k8s_config.ConfigException:
            logger.warning("No Kubernetes config found — query session features disabled")
            self.core_v1 = None

    def _get_session_config(self) -> dict:
        """Get session configuration from app config."""
        analyst_config = self.config_manager.get_config("cloud_analyst") or {}
        return analyst_config.get("session", {})

    # ── Pod Pool Management ────────────────────────────────────────────

    def _get_pool_size(self) -> int:
        """Get configured pool size (0 = disabled)."""
        config = self._get_session_config()
        return config.get("pool_size", 0)

    async def start_pool(self):
        """Initialize the pod pool on app startup.

        Creates pool pods up to the configured pool_size. Each pool pod is
        a pre-warmed query engine instance with plugins installed and service
        running, but NO cloud credentials. Pods are claimed instantly when
        a user starts a new chat.
        """
        # Skip pool if LLM provider is not configured (no API key = analyst unusable)
        from app.deps import is_analyst_ready
        if not is_analyst_ready():
            logger.info("Session pod pool skipped (Cloud Analyst not configured)")
            return

        pool_size = self._get_pool_size()
        if pool_size <= 0:
            logger.info("Session pod pool disabled (pool_size=0)")
            return

        logger.info("Initializing session pod pool (target size: %d)", pool_size)

        # Clean up any orphaned pool pods from previous runs
        await self._cleanup_orphaned_pool_pods()

        # Fill pool to target size
        await self._replenish_pool()

    async def _cleanup_orphaned_pool_pods(self):
        """Delete pool pods left over from a previous app instance."""
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="managed-by=qubiva-analyst,pool=true",
            )
            for pod in pods.items:
                try:
                    self.core_v1.delete_namespaced_pod(
                        name=pod.metadata.name,
                        namespace=self.namespace,
                        grace_period_seconds=0,
                    )
                    logger.info("Cleaned up orphaned pool pod: %s", pod.metadata.name)
                except k8s_client.ApiException:
                    pass
        except Exception as e:
            logger.warning("Failed to clean up orphaned pool pods: %s", e)

    async def _replenish_pool(self):
        """Ensure the pool has enough ready pods."""
        # Skip if LLM provider is not configured
        from app.deps import is_analyst_ready
        if not is_analyst_ready():
            return

        pool_size = self._get_pool_size()
        if pool_size <= 0:
            return

        async with self._pool_replenish_lock:
            current = len(self._pool)
            needed = pool_size - current
            if needed <= 0:
                return

            logger.info(
                "Replenishing pod pool: %d/%d (creating %d)",
                current, pool_size, needed,
            )
            for _ in range(needed):
                await self._create_pool_pod()

    async def _create_pool_pod(self):
        """Create a single pre-warmed pool pod."""
        pool_id = uuid.uuid4().hex[:10]
        pod_name = f"analyst-pool-{pool_id}"

        try:
            # Build env vars — install all plugins since we don't know the platform yet
            env_vars = self._build_pod_env_vars_lazy(cloud_platform=None)

            # Create pod with pool label
            pod = self._build_pod_spec(pod_name, env_vars, pool=True)
            self.core_v1.create_namespaced_pod(
                namespace=self.namespace, body=pod
            )
            logger.info("Created pool pod: %s", pod_name)

            # Track in pool with a placeholder SessionPod
            session = SessionPod(
                conversation_id=f"pool-{pool_id}",
                pod_name=pod_name,
                namespace=self.namespace,
                cloud_platform=None,
                status="starting",
            )
            self._pool[pod_name] = session

            # Wait for readiness in background
            asyncio.create_task(self._wait_for_pool_pod_ready(pod_name))

        except Exception as e:
            logger.error("Failed to create pool pod %s: %s", pod_name, e)

    async def _wait_for_pool_pod_ready(self, pod_name: str, timeout: int = 180):
        """Wait for a pool pod to become ready."""
        session = self._pool.get(pod_name)
        if not session:
            return

        start = time.time()
        while time.time() - start < timeout:
            try:
                pod = self.core_v1.read_namespaced_pod_status(
                    name=pod_name, namespace=self.namespace
                )
                if pod.status.phase in ("Failed", "Unknown"):
                    logger.warning("Pool pod %s failed", pod_name)
                    self._pool.pop(pod_name, None)
                    return

                if pod.status.container_statuses:
                    cs = pod.status.container_statuses[0]
                    if cs.ready:
                        session.status = "ready"
                        session.pod_ip = pod.status.pod_ip
                        logger.info("Pool pod %s ready at %s", pod_name, session.pod_ip)
                        return

                    if cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason or ""
                        fatal = {"ErrImagePull", "ImagePullBackOff",
                                 "InvalidImageName", "CrashLoopBackOff"}
                        if reason in fatal:
                            logger.warning("Pool pod %s fatal: %s", pod_name, reason)
                            self._pool.pop(pod_name, None)
                            return

            except k8s_client.ApiException as e:
                if e.status == 404:
                    self._pool.pop(pod_name, None)
                    return

            await asyncio.sleep(3)

        # Timeout — remove from pool and delete
        logger.warning("Pool pod %s timed out waiting for ready", pod_name)
        self._pool.pop(pod_name, None)
        try:
            self.core_v1.delete_namespaced_pod(
                name=pod_name, namespace=self.namespace, grace_period_seconds=0
            )
        except Exception:
            pass

    def _claim_pool_pod(self, conversation_id: str, user: Optional[str] = None) -> Optional[SessionPod]:
        """Try to claim a ready pod from the pool.

        Returns a SessionPod if successful, None if pool is empty or no ready pods.
        """
        for pod_name, session in list(self._pool.items()):
            if session.status == "ready":
                # Claim it
                self._pool.pop(pod_name)
                session.conversation_id = conversation_id
                session.user = user
                session.last_activity = time.time()
                self._sessions[conversation_id] = session
                logger.info(
                    "Claimed pool pod %s for conversation %s",
                    pod_name, conversation_id[:12],
                )
                # Trigger replenishment in background
                asyncio.create_task(self._replenish_pool())
                return session
        return None

    async def on_config_change(self, changed_keys: list):
        """React to config changes detected by ConfigManager.

        If cloud_analyst config changed, adjust the analyst pod pool:
        - Pool size increased: replenish adds more pods
        - Pool size decreased: drain excess idle pods
        - Pool disabled (size=0 or no LLM key): drain all idle pods
        """
        if "cloud_analyst" not in changed_keys:
            return

        # Re-read config
        from app.deps import is_analyst_ready
        ready = is_analyst_ready()
        new_size = self._get_pool_size() if ready else 0
        idle = len(self._pool)

        logger.info(
            "Analyst pool config changed — target size: %d, current idle: %d, analyst ready: %s",
            new_size, idle, ready,
        )

        if new_size <= 0:
            # Pool disabled — drain all idle pods
            for pod_name in list(self._pool.keys()):
                pod = self._pool.pop(pod_name, None)
                if pod:
                    try:
                        self.core_v1.delete_namespaced_pod(
                            name=pod_name, namespace=self.namespace,
                            grace_period_seconds=0,
                        )
                    except Exception:
                        pass
                    logger.info("Drained analyst pool pod (pool disabled): %s", pod_name)
            return

        if idle > new_size:
            # Shrink — remove excess idle pods (oldest first)
            excess = idle - new_size
            pods_by_age = sorted(
                self._pool.items(),
                key=lambda kv: kv[1].created_at,
            )
            for pod_name, _ in pods_by_age[:excess]:
                self._pool.pop(pod_name, None)
                try:
                    self.core_v1.delete_namespaced_pod(
                        name=pod_name, namespace=self.namespace,
                        grace_period_seconds=0,
                    )
                except Exception:
                    pass
                logger.info("Drained excess analyst pool pod: %s", pod_name)
        elif idle < new_size:
            # Grow — replenish will create more pods
            await self._replenish_pool()

    async def pool_maintenance_loop(self):
        """Background loop to maintain pool size and clean up stale pool pods.

        Run this as a periodic task (e.g., every 30 seconds).
        """
        pool_size = self._get_pool_size()
        if pool_size <= 0:
            return

        # Remove pool pods that are stuck in starting state too long (>3min)
        stale_threshold = time.time() - 180
        for pod_name, session in list(self._pool.items()):
            if session.status == "starting" and session.created_at < stale_threshold:
                logger.warning("Removing stale pool pod: %s", pod_name)
                self._pool.pop(pod_name, None)
                try:
                    self.core_v1.delete_namespaced_pod(
                        name=pod_name, namespace=self.namespace, grace_period_seconds=0
                    )
                except Exception:
                    pass

        # Replenish if needed
        await self._replenish_pool()

    def get_pool_summary(self) -> dict:
        """Return analyst pool status in the same format as RunnerPoolManager."""
        from app.deps import is_analyst_ready
        ready = is_analyst_ready()
        pool_size = self._get_pool_size() if ready else 0

        if pool_size <= 0:
            return {}

        ready_count = sum(1 for s in self._pool.values() if s.status == "ready")
        starting_count = sum(1 for s in self._pool.values() if s.status == "starting")
        busy_count = sum(1 for s in self._sessions.values() if s.status in ("starting", "ready"))

        return {
            "analyst": {
                "enabled": True,
                "target_size": pool_size,
                "ready": ready_count,
                "starting": starting_count,
                "busy": busy_count,
                "execution_mode": "pool_with_fallback",
            }
        }

    def count_active_sessions(self, user: str) -> int:
        """Count active (non-terminated) sessions for a user."""
        return sum(
            1 for s in self._sessions.values()
            if s.user == user and s.status in ("starting", "ready")
        )

    async def create_session_pod(
        self,
        conversation_id: str,
        cloud_platform: Optional[str] = None,
        user: Optional[str] = None,
    ) -> SessionPod:
        """Create a cloud query pod for a chat session (lazy connect).

        Tries to claim a pre-warmed pod from the pool first for instant
        readiness. Falls back to creating a new pod if pool is empty.

        Args:
            conversation_id: Unique conversation identifier.
            cloud_platform: Optional hint for primary platform (used for plugin install).
            user: Username who owns this session.

        Returns:
            SessionPod tracking object.
        """
        # Try to claim a ready pod from the pool
        claimed = self._claim_pool_pod(conversation_id, user)
        if claimed:
            claimed.cloud_platform = cloud_platform
            logger.info(
                "Instant session from pool pod %s for conversation %s",
                claimed.pod_name, conversation_id[:12],
            )
            return claimed

        # No pool pod available — create a new one
        short_id = conversation_id[:12].lower().replace("-", "")
        pod_name = f"analyst-{short_id}"

        session = SessionPod(
            conversation_id=conversation_id,
            pod_name=pod_name,
            namespace=self.namespace,
            cloud_platform=cloud_platform,
            user=user,
        )
        self._sessions[conversation_id] = session

        try:
            # Build minimal env vars — no credentials, just query engine setup
            env_vars = self._build_pod_env_vars_lazy(cloud_platform)

            # Create the K8s pod
            pod = self._build_pod_spec(pod_name, env_vars)
            self.core_v1.create_namespaced_pod(
                namespace=self.namespace, body=pod
            )
            logger.info("Created analyst session pod (lazy): %s", pod_name)

            # Wait for pod to be ready in background
            asyncio.create_task(
                self._wait_for_pod_ready(conversation_id, pod_name)
            )

            return session

        except Exception as e:
            session.status = "error"
            session.error_message = str(e)
            logger.error("Failed to create session pod %s: %s", pod_name, e)
            return session

    async def connect_account(
        self,
        conversation_id: str,
        platform: str,
        account_id: str,
        project_name: str,
    ) -> dict:
        """Dynamically connect a cloud account to an existing session pod.

        Decrypts credentials, writes a connection .spc config file into the pod,
        and creates/updates an aggregator if multiple accounts of the same
        platform are connected.

        Args:
            conversation_id: Session to add the account to.
            platform: Cloud platform (aws, gcp, azure).
            account_id: Cloud account identifier.
            project_name: Qubiva project containing the account.

        Returns:
            Dict with 'status' on success or 'error' on failure.
        """
        session = self._sessions.get(conversation_id)
        if not session:
            return {"error": "No active session for this conversation"}
        if session.status != "ready":
            return {"error": f"Session is not ready (status: {session.status})"}

        # Check if already connected
        if account_id in session.connected_accounts:
            return {"status": "already_connected", "account_id": account_id}

        session.last_activity = time.time()

        try:
            # 1. Decrypt credentials
            auth = MultiCloudAuthentication(
                platform, self.project_manager, project_name, account_id
            )
            await auth.initialize()
            env_vars = await auth.get_auth_env_vars()

            # 2. Build connection config
            safe_id = account_id.replace("-", "_").replace(":", "_")
            conn_name = f"{platform}_{safe_id}"
            spc_content = self._build_single_connection_spc(
                platform, conn_name, env_vars
            )

            # 3. Write .spc file into pod via exec
            spc_path = f"/home/runner/config/{conn_name}.spc"
            write_result = await self.exec_in_pod(
                conversation_id,
                ["/bin/sh", "-c", f"cat > {spc_path} << 'SPCEOF'\n{spc_content}\nSPCEOF"],
                timeout=15,
            )
            if "error" in write_result:
                return {"error": f"Failed to write config: {write_result['error']}"}

            # 4. Also write env vars the plugin needs (for AWS/GCP/Azure auth)
            env_script = self._build_env_export_script(platform, env_vars, conn_name)
            if env_script:
                env_path = f"/home/runner/config/{conn_name}_env.sh"
                await self.exec_in_pod(
                    conversation_id,
                    ["/bin/sh", "-c", f"cat > {env_path} << 'ENVEOF'\n{env_script}\nENVEOF"],
                    timeout=15,
                )

            # 5. Track the connection
            session.connected_accounts[account_id] = platform

            # 6. Install plugin if not already present
            await self._ensure_plugin_installed(conversation_id, platform)

            # 7. Write/update the default platform connection (e.g. "aws")
            #    so that bare table names like aws_s3_bucket resolve correctly.
            #    - Single account: direct connection with credentials
            #    - Multiple accounts: aggregator over all named connections
            await self._write_default_platform_connection(
                conversation_id, platform, session, env_vars
            )

            logger.info(
                "Connected account %s (%s) to session %s",
                account_id, platform, session.pod_name,
            )
            return {
                "status": "connected",
                "account_id": account_id,
                "connection_name": conn_name,
                "total_connected": len(session.connected_accounts),
            }

        except Exception as e:
            logger.error(
                "Failed to connect account %s to session %s: %s",
                account_id, session.pod_name, e,
            )
            return {"error": f"Failed to connect account: {e}"}

    def _build_single_connection_spc(
        self, platform: str, conn_name: str, env_vars: dict
    ) -> str:
        """Build an .spc connection block for a single account."""
        plugin = platform  # aws, gcp, azure
        lines = [f'connection "{conn_name}" {{', f'  plugin = "{plugin}"']

        if platform == "aws":
            region = env_vars.get("AWS_DEFAULT_REGION", "us-east-1")
            access_key = env_vars.get("AWS_ACCESS_KEY_ID", "")
            secret_key = env_vars.get("AWS_SECRET_ACCESS_KEY", "")
            session_token = env_vars.get("AWS_SESSION_TOKEN", "")
            lines.append(f'  access_key = "{access_key}"')
            lines.append(f'  secret_key = "{secret_key}"')
            if session_token:
                lines.append(f'  session_token = "{session_token}"')
            lines.append(f'  regions = ["{region}"]')
        elif platform == "gcp":
            # Write credentials JSON to a file, reference it
            creds_json = env_vars.get("GOOGLE_APPLICATION_CREDENTIALS_CONTENT", "")
            if creds_json:
                lines.append(f'  credentials = <<-EOF\n{creds_json}\nEOF')
            project = env_vars.get("GCP_PROJECT", env_vars.get("CLOUDSDK_CORE_PROJECT", ""))
            if project:
                lines.append(f'  project = "{project}"')
        elif platform == "azure":
            tenant_id = env_vars.get("ARM_TENANT_ID", env_vars.get("AZURE_TENANT_ID", ""))
            client_id = env_vars.get("ARM_CLIENT_ID", env_vars.get("AZURE_CLIENT_ID", ""))
            client_secret = env_vars.get("ARM_CLIENT_SECRET", env_vars.get("AZURE_CLIENT_SECRET", ""))
            sub_id = env_vars.get("ARM_SUBSCRIPTION_ID", env_vars.get("CLOUD_ACCOUNT_ID", ""))
            if tenant_id:
                lines.append(f'  tenant_id = "{tenant_id}"')
            if client_id:
                lines.append(f'  client_id = "{client_id}"')
            if client_secret:
                lines.append(f'  client_secret = "{client_secret}"')
            if sub_id:
                lines.append(f'  subscription_id = "{sub_id}"')

        lines.append("}")
        return "\n".join(lines)

    def _build_env_export_script(
        self, platform: str, env_vars: dict, conn_name: str
    ) -> Optional[str]:
        """Build shell export commands for cloud auth env vars (if needed)."""
        # For AWS, credentials are embedded in .spc — no env vars needed
        # For GCP/Azure, some plugins may read env vars too
        return None

    async def _ensure_plugin_installed(
        self, conversation_id: str, platform: str
    ):
        """Install a query engine plugin in the pod if not already present."""
        check = await self.exec_in_pod(
            conversation_id,
            ["/bin/sh", "-c",
             f"ls /home/runner/plugins/hub.steampipe.io/plugins/turbot/{platform}* 2>/dev/null && echo INSTALLED || echo MISSING"],
            timeout=10,
        )
        output = check.get("output", "")
        if "INSTALLED" in output:
            return  # Already installed

        versions = self._get_query_engine_versions(platform)
        pl_version = versions.get("plugin_version", "latest")
        install_cmd = f"{platform}@{pl_version}" if pl_version != "latest" else platform

        logger.info("Installing %s plugin in session pod", platform)
        await self.exec_in_pod(
            conversation_id,
            ["/bin/sh", "-c",
             f"export HOME=/home/runner && export PATH=/home/runner/bin:$PATH && "
             f"sp plugin install {install_cmd} 2>&1"],
            timeout=120,
        )

    async def _write_default_platform_connection(
        self,
        conversation_id: str,
        platform: str,
        session: SessionPod,
        env_vars: dict,
    ):
        """Write/update the bare platform connection (e.g. connection "aws").

        This ensures unqualified table names like `aws_s3_bucket` resolve to real
        credentials instead of falling through to the empty default credential chain.

        - Single account connected: direct connection with embedded credentials.
        - Multiple accounts: aggregator over all named connections, plus
          a separate ``{platform}_all`` alias.
        """
        same_platform_ids = [
            aid for aid, p in session.connected_accounts.items() if p == platform
        ]

        spc_path = f"/home/runner/config/{platform}.spc"

        if len(same_platform_ids) == 1:
            # Single account — write a direct connection named after the bare platform
            spc_content = self._build_single_connection_spc(platform, platform, env_vars)
        else:
            # Multiple accounts — write an aggregator named after the bare platform
            conn_names = []
            for aid in same_platform_ids:
                safe_id = aid.replace("-", "_").replace(":", "_")
                conn_names.append(f"{platform}_{safe_id}")
            conns_str = ", ".join(f'"{c}"' for c in conn_names)
            spc_content = (
                f'connection "{platform}" {{\n'
                f'  plugin      = "{platform}"\n'
                f'  type        = "aggregator"\n'
                f'  connections = [{conns_str}]\n'
                f'}}'
            )

            # Also write a {platform}_all alias (for explicit cross-account queries)
            agg_all_path = f"/home/runner/config/{platform}_all.spc"
            agg_all_spc = (
                f'connection "{platform}_all" {{\n'
                f'  plugin      = "{platform}"\n'
                f'  type        = "aggregator"\n'
                f'  connections = [{conns_str}]\n'
                f'}}'
            )
            await self.exec_in_pod(
                conversation_id,
                ["/bin/sh", "-c", f"cat > {agg_all_path} << 'SPCEOF'\n{agg_all_spc}\nSPCEOF"],
                timeout=15,
            )

        await self.exec_in_pod(
            conversation_id,
            ["/bin/sh", "-c", f"cat > {spc_path} << 'SPCEOF'\n{spc_content}\nSPCEOF"],
            timeout=15,
        )

        # Restart query service so it re-reads config files.
        # The file watcher is unreliable — a restart guarantees the new
        # connections are loaded before the next query.
        logger.info("Restarting query service in pod %s", session.pod_name)
        restart_result = await self.exec_in_pod(
            conversation_id,
            ["/bin/sh", "-c",
             "export HOME=/home/runner && export PATH=/home/runner/bin:$PATH && "
             "sp service restart --force 2>&1"],
            timeout=30,
        )
        if "error" in restart_result:
            logger.error("Query service restart failed in pod %s: %s", session.pod_name, restart_result["error"])
        else:
            output = restart_result.get("output", "")
            if "Error" in output:
                logger.error("Query service restart error in pod %s: %s", session.pod_name, output[:200])
            else:
                logger.info("Query service restart succeeded in pod %s", session.pod_name)
        # Wait for the service port to come back up
        await asyncio.sleep(3)

        # Drop cached asyncpg connection — next query will reconnect
        old_conn = self._connections.pop(conversation_id, None)
        if old_conn and not old_conn.is_closed():
            try:
                await old_conn.close()
            except Exception:
                pass

    def get_connected_accounts(self, conversation_id: str) -> List[dict]:
        """Return the list of currently connected accounts for a session."""
        session = self._sessions.get(conversation_id)
        if not session:
            return []
        return [
            {"account_id": aid, "platform": p}
            for aid, p in session.connected_accounts.items()
        ]

    def _get_query_engine_versions(self, cloud_platform: str) -> dict:
        """Get query engine/plugin versions from app config.

        Returns dict with query_engine_version, plugin_version keys.
        Falls back to 'latest' if not configured.
        """
        versions_config = self.config_manager.get_config("query_engine_versions") or {}
        query_engine_version = versions_config.get("query_engine_version", "latest")
        plugin_versions = versions_config.get("plugin_versions", {})
        plugin_version = plugin_versions.get(cloud_platform, "latest")
        return {
            "query_engine_version": query_engine_version,
            "plugin_version": plugin_version,
        }

    def _build_pod_env_vars_lazy(
        self,
        cloud_platform: Optional[str] = None,
    ) -> List[k8s_client.V1EnvVar]:
        """Build minimal K8s env vars for a lazy-connect session pod.

        No credentials — just query engine setup. Accounts are connected later
        via connect_account() which writes .spc files into the running pod.
        """
        versions_config = self.config_manager.get_config("query_engine_versions") or {}
        query_engine_version = versions_config.get("query_engine_version", "latest")

        env_vars = [
            k8s_client.V1EnvVar(name="SESSION_MODE", value="interactive"),
            k8s_client.V1EnvVar(name="QUERY_ENGINE_VERSION", value=query_engine_version),
        ]

        # Hint which plugins to pre-install (speeds up first connect_account)
        if cloud_platform:
            plugin_versions = versions_config.get("plugin_versions", {})
            plugin_version = plugin_versions.get(cloud_platform, "latest")
            env_vars.append(k8s_client.V1EnvVar(name="CLOUD_PLATFORM", value=cloud_platform))
            env_vars.append(k8s_client.V1EnvVar(name="PLUGIN_VERSION", value=plugin_version))
        else:
            # Multi-platform: install all plugins
            env_vars.append(k8s_client.V1EnvVar(name="CLOUD_PLATFORM", value="all"))

        return env_vars

    def _build_pod_spec(
        self,
        pod_name: str,
        env_vars: List[k8s_client.V1EnvVar],
        pool: bool = False,
    ) -> k8s_client.V1Pod:
        """Build the K8s Pod spec for a cloud query session.

        Args:
            pool: If True, adds pool=true label for pool management.
        """
        container = k8s_client.V1Container(
            name="query-engine",
            image=self.runner_image,
            image_pull_policy="IfNotPresent",
            # Override the runner's default entrypoint to start in service mode
            command=["/bin/sh", "-c"],
            args=[self._session_entrypoint_script()],
            env=env_vars,
            ports=[
                k8s_client.V1ContainerPort(
                    container_port=self.QUERY_ENGINE_PG_PORT,
                    name="postgres",
                )
            ],
            resources=k8s_client.V1ResourceRequirements(
                requests={"memory": "512Mi", "cpu": "250m"},
                limits={"memory": "2Gi", "cpu": "1"},
            ),
            readiness_probe=k8s_client.V1Probe(
                tcp_socket=k8s_client.V1TCPSocketAction(
                    port=self.QUERY_ENGINE_PG_PORT,
                ),
                initial_delay_seconds=10,
                period_seconds=5,
                failure_threshold=12,  # Up to 70s total startup time
            ),
        )

        labels = {
            "app": "qubiva",
            "component": "analyst-session",
            "managed-by": "qubiva-analyst",
        }
        if pool:
            labels["pool"] = "true"

        return k8s_client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=k8s_client.V1ObjectMeta(
                name=pod_name,
                namespace=self.namespace,
                labels=labels,
            ),
            spec=k8s_client.V1PodSpec(
                containers=[container],
                restart_policy="Never",
                service_account_name=os.environ.get(
                    "RUNNER_SERVICE_ACCOUNT", "qubiva-runner"
                ),
                # Auto-terminate after 30min if cleanup fails
                active_deadline_seconds=1800,
            ),
        )

    def _session_entrypoint_script(self) -> str:
        """Shell script that starts the query engine in service (database) mode.

        Lazy connect version:
        1. Downloads and installs the query engine binary (renamed to 'sp')
        2. Installs plugin(s) based on CLOUD_PLATFORM hint
        3. Creates empty config directory (connections added later via exec)
        4. Starts the query service on port 9193
        5. Sleeps to keep the container alive
        """
        return """
set -e

export HOME="/home/runner"
export STEAMPIPE_INSTALL_DIR="/home/runner"
export STEAMPIPE_HOME="/home/runner/.steampipe"
export PATH="/home/runner/bin:$PATH"
export STEAMPIPE_UPDATE_CHECK=false
export STEAMPIPE_TELEMETRY=none

PLATFORM="${CLOUD_PLATFORM:-aws}"
SP_VERSION="${QUERY_ENGINE_VERSION:-latest}"
PL_VERSION="${PLUGIN_VERSION:-latest}"

# Download and install query engine binary
echo "Installing query engine ${SP_VERSION}..."
mkdir -p "$HOME/bin"
cd /tmp
if [ "$SP_VERSION" = "latest" ]; then
    curl -fsSL "https://github.com/turbot/steampipe/releases/latest/download/steampipe_linux_amd64.tar.gz" -o steampipe.tar.gz
else
    curl -fsSL "https://github.com/turbot/steampipe/releases/download/${SP_VERSION}/steampipe_linux_amd64.tar.gz" -o steampipe.tar.gz
fi
tar -xzf steampipe.tar.gz
mv steampipe "$HOME/bin/sp"
chmod +x "$HOME/bin/sp"
rm -f steampipe.tar.gz
cd "$HOME"

# Install plugin(s) — pre-install so connect_account is fast
if [ "$PLATFORM" = "all" ]; then
    echo "Installing all cloud plugins..."
    for p in aws gcp azure; do
        sp plugin install "$p" 2>&1 || echo "Warning: Failed to install $p plugin"
    done
else
    if [ "$PL_VERSION" = "latest" ]; then
        echo "Installing $PLATFORM plugin (latest)..."
        sp plugin install "$PLATFORM" 2>&1 || true
    else
        echo "Installing $PLATFORM plugin @ ${PL_VERSION}..."
        sp plugin install "${PLATFORM}@${PL_VERSION}" 2>&1 || true
    fi
fi

# Remove default .spc files created by plugin install — they define empty
# connections that use the default credential chain (env vars / IMDS) and
# would shadow the explicit-credential connections we write via connect_account.
# In the query engine v2 the config dir is $HOME/config/ (not .steampipe/config/).
rm -f "$HOME/config/aws.spc" \
      "$HOME/config/gcp.spc" \
      "$HOME/config/azure.spc"
echo "Cleaned up default plugin .spc files"

# Start query service in database mode — no connections yet
echo "Starting query service on port 9193 (lazy connect mode)..."
sp service start --database-port 9193 --database-listen network --database-password steampipe

echo "Query session ready on port 9193 (no connections — use connect_account)"

# Keep container alive — query service runs in background
while true; do sleep 60; done
""".strip()

    async def _wait_for_pod_ready(
        self, conversation_id: str, pod_name: str, timeout: int = 120
    ):
        """Wait for the session pod to become ready."""
        session = self._sessions.get(conversation_id)
        if not session:
            return

        start = time.time()
        while time.time() - start < timeout:
            try:
                pod = self.core_v1.read_namespaced_pod_status(
                    name=pod_name, namespace=self.namespace
                )

                # Check for fatal states
                if pod.status.phase in ("Failed", "Unknown"):
                    session.status = "error"
                    session.error_message = f"Pod entered {pod.status.phase} phase"
                    return

                # Check container readiness
                if pod.status.container_statuses:
                    cs = pod.status.container_statuses[0]
                    if cs.ready:
                        session.status = "ready"
                        session.pod_ip = pod.status.pod_ip
                        logger.info(
                            "Session pod %s ready at %s",
                            pod_name, session.pod_ip,
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
                            session.status = "error"
                            session.error_message = (
                                cs.state.waiting.message or reason
                            )
                            return

            except k8s_client.ApiException as e:
                if e.status == 404:
                    session.status = "error"
                    session.error_message = "Pod was deleted before becoming ready"
                    return
                logger.warning("Error checking pod %s: %s", pod_name, e.reason)

            await asyncio.sleep(3)

        # Timeout
        session.status = "error"
        session.error_message = f"Pod did not become ready within {timeout}s"
        logger.warning("Session pod %s timed out waiting for readiness", pod_name)

    async def execute_query(
        self,
        conversation_id: str,
        sql: str,
        timeout: Optional[int] = None,
    ) -> QueryResult:
        """Execute a SQL query against the session's cloud query pod.

        Args:
            conversation_id: Conversation whose pod to query.
            sql: SQL query to execute.
            timeout: Query timeout in seconds (default from config).

        Returns:
            QueryResult with rows, columns, and metadata.
        """
        session = self._sessions.get(conversation_id)
        if not session:
            return QueryResult(
                columns=[], rows=[], row_count=0,
                error="No active session for this conversation",
            )

        if session.status != "ready":
            return QueryResult(
                columns=[], rows=[], row_count=0,
                error=f"Session is not ready (status: {session.status})",
            )

        session_config = self._get_session_config()
        if timeout is None:
            timeout = session_config.get("query_timeout_seconds", 120)
        max_rows = session_config.get("max_result_rows", 500)

        session.last_activity = time.time()

        try:
            conn = await self._get_connection(conversation_id)

            # Execute with timeout
            rows = await asyncio.wait_for(
                conn.fetch(sql),
                timeout=timeout,
            )

            if not rows:
                return QueryResult(columns=[], rows=[], row_count=0)

            columns = list(rows[0].keys())
            truncated = len(rows) > max_rows
            result_rows = [dict(r) for r in rows[:max_rows]]

            # Convert non-serializable types to strings
            for row in result_rows:
                for key, value in row.items():
                    if not isinstance(value, (str, int, float, bool, type(None), list, dict)):
                        row[key] = str(value)

            return QueryResult(
                columns=columns,
                rows=result_rows,
                row_count=len(rows),
                truncated=truncated,
            )

        except asyncio.TimeoutError:
            return QueryResult(
                columns=[], rows=[], row_count=0,
                error=f"Query timed out after {timeout}s",
            )
        except asyncpg.PostgresError as e:
            return QueryResult(
                columns=[], rows=[], row_count=0,
                error=f"Query error: {e}",
            )
        except Exception as e:
            # Connection may be stale — drop it so next query reconnects
            self._connections.pop(conversation_id, None)
            return QueryResult(
                columns=[], rows=[], row_count=0,
                error=f"Execution error: {e}",
            )

    async def _get_connection(self, conversation_id: str) -> asyncpg.Connection:
        """Get or create an asyncpg connection to the session pod."""
        conn = self._connections.get(conversation_id)
        if conn and not conn.is_closed():
            return conn

        session = self._sessions[conversation_id]
        if not session.pod_ip:
            raise RuntimeError("Pod IP not available")

        conn = await asyncpg.connect(
            host=session.pod_ip,
            port=self.QUERY_ENGINE_PG_PORT,
            user=self.QUERY_ENGINE_PG_USER,
            password=self.QUERY_ENGINE_PG_PASSWORD,
            database=self.QUERY_ENGINE_PG_DATABASE,
        )
        self._connections[conversation_id] = conn
        return conn

    async def exec_in_pod(
        self,
        conversation_id: str,
        command: List[str],
        timeout: int = 300,
    ) -> dict:
        """Execute a command in the session pod via K8s exec.

        Args:
            conversation_id: Conversation whose pod to run the command in.
            command: Command and args as a list (passed to K8s exec).
            timeout: Timeout in seconds.

        Returns:
            Dict with 'output' key on success, 'error' key on failure.
        """
        session = self._sessions.get(conversation_id)
        if not session:
            return {"error": "No active session for this conversation"}
        if session.status != "ready":
            return {"error": f"Session is not ready (status: {session.status})"}

        session.last_activity = time.time()

        try:
            from kubernetes.stream import stream as k8s_stream

            def _exec():
                return k8s_stream(
                    self.core_v1.connect_get_namespaced_pod_exec,
                    name=session.pod_name,
                    namespace=self.namespace,
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
            return {"error": f"Command execution failed: {e}"}

    async def get_session_status(self, conversation_id: str) -> str:
        """Get the current status of a session pod."""
        session = self._sessions.get(conversation_id)
        if not session:
            return "terminated"
        return session.status

    async def get_session_error(self, conversation_id: str) -> Optional[str]:
        """Get error message if session is in error state."""
        session = self._sessions.get(conversation_id)
        if session:
            return session.error_message
        return None

    async def destroy_session_pod(self, conversation_id: str):
        """Destroy the session pod and clean up resources."""
        session = self._sessions.pop(conversation_id, None)
        if not session:
            return

        # Close DB connection
        conn = self._connections.pop(conversation_id, None)
        if conn and not conn.is_closed():
            try:
                await conn.close()
            except Exception:
                pass

        # Delete the K8s pod
        try:
            self.core_v1.delete_namespaced_pod(
                name=session.pod_name,
                namespace=self.namespace,
                body=k8s_client.V1DeleteOptions(
                    grace_period_seconds=5,
                ),
            )
            logger.info("Destroyed session pod: %s", session.pod_name)
        except k8s_client.ApiException as e:
            if e.status != 404:
                logger.warning(
                    "Error deleting session pod %s: %s",
                    session.pod_name, e.reason,
                )

        session.status = "terminated"

    async def cleanup_idle_sessions(self):
        """Destroy pods that have been idle beyond the timeout.

        Should be called periodically from a background task.
        """
        session_config = self._get_session_config()
        idle_timeout = session_config.get("idle_timeout_seconds", 900)
        now = time.time()

        idle_ids = [
            cid for cid, session in self._sessions.items()
            if session.status in ("ready", "error")
            and (now - session.last_activity) > idle_timeout
        ]

        for cid in idle_ids:
            logger.info(
                "Cleaning up idle session pod for conversation %s", cid
            )
            await self.destroy_session_pod(cid)

    async def cleanup_all_sessions(self):
        """Destroy all active session pods. Called on app shutdown."""
        conversation_ids = list(self._sessions.keys())
        for cid in conversation_ids:
            await self.destroy_session_pod(cid)
