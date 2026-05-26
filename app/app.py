"""
Qubiva application entry point.

Creates the FastAPI app with lifespan, exception handlers, static file mount,
template globals, and includes all route modules.
"""

import logging
import os

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from fastapi_utils.tasks import repeat_every

from app.database_generic_operator import MongoDBManager
from app.app_config_manager import ConfigManager
from app.deps import (
    project_manager,
    request_tracker,
    scheduler,
    log_persistence,
    schema_registry,
    session_manager,
    chat_manager,
    master_admin,
    templates,
    get_app_base_url,
    iac_pool_manager,
    discovery_pool_manager,
    ai_gateway_manager,
)

# Import all route modules
from app.routes import (
    health,
    internal,
    stats,
    auth_routes,
    org,
    projects,
    github,
    cloud_accounts,
    workspaces,
    requests,
    discovery,
    tasks,
    alerts,
    sso,
    analyst,
    dashboard,
    ai_governance,
    project_tokens,
    run_actions,
)

log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
logger = logging.getLogger("uvicorn.error")
logger.setLevel(log_level)

# Silence websocket ping/pong keepalive logs


class WebSocketPingPongFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        # Filter out ping/pong messages
        if any(keyword in message for keyword in ['keepalive ping', 'keepalive pong', '> PING', '< PONG', '% sending', '% received']):
            return False
        return True


# Apply filter to all loggers that might emit websocket messages
for logger_name in ["websockets", "websockets.protocol", "websockets.server", "uvicorn.error", "uvicorn.access"]:
    ws_logger = logging.getLogger(logger_name)
    ws_logger.addFilter(WebSocketPingPongFilter())


def _store_initial_admin_secret(password: str):
    """Store the initial admin password in a K8s Secret (ArgoCD pattern).

    Creates a Secret named 'qubiva-initial-admin-secret' so operators can
    retrieve it with kubectl. The password is never written to logs.
    """
    try:
        from kubernetes import client as k8s_client, config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()

        # kubernetes-python-client v29+ bug: load_incluster_config() writes
        # the token to api_key['authorization'] but auth_settings() checks
        # api_key['BearerToken'], so no auth header is sent → system:anonymous.
        # Fix: keep both keys in sync.
        cfg = k8s_client.Configuration.get_default_copy()
        if 'authorization' in cfg.api_key and 'BearerToken' not in cfg.api_key:
            cfg.api_key['BearerToken'] = cfg.api_key['authorization']
        api_client = k8s_client.ApiClient(configuration=cfg)

        namespace = os.environ.get("K8S_NAMESPACE", "default")
        secret = k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(
                name="qubiva-initial-admin-secret",
                namespace=namespace,
                labels={"app": "qubiva", "component": "bootstrap"},
            ),
            string_data={"password": password},
        )
        core_v1 = k8s_client.CoreV1Api(api_client=api_client)
        try:
            core_v1.read_namespaced_secret("qubiva-initial-admin-secret", namespace)
            core_v1.replace_namespaced_secret("qubiva-initial-admin-secret", namespace, secret)
        except k8s_client.ApiException as e:
            if e.status == 404:
                core_v1.create_namespaced_secret(namespace, secret)
            else:
                raise
        logger.info("Initial admin password stored in Secret 'qubiva-initial-admin-secret'")
    except Exception as e:
        logger.error(f"Could not create K8s Secret for initial password: {e}")
        logger.error("  Admin password cannot be retrieved. Delete the admin user from the database and restart to regenerate.")


async def recover_orphaned_requests():
    """
    On startup, find requests stuck in 'in progress' or 'queued' state and mark them
    as 'execution failed' since the container restart means monitoring was lost.
    """
    try:
        _db_manager = MongoDBManager()
        collection_name = "requests"

        # Find all requests stuck in non-terminal states
        orphaned_states = ["in progress", "queued"]
        orphaned_requests = await _db_manager.find_documents(
            collection_name,
            {"state": {"$in": orphaned_states}}
        )

        if not orphaned_requests:
            logger.info("No orphaned requests found during startup recovery")
            return

        logger.warning(f"Found {len(orphaned_requests)} orphaned requests during startup")

        # Mark them as execution failed with a clear reason
        recovery_count = 0
        for request in orphaned_requests:
            request_id = request.get("request_id")
            old_state = request.get("state")

            try:
                # Update state and add error details
                await _db_manager.update_document(
                    collection_name,
                    {"request_id": request_id},
                    {
                        "state": "execution failed",
                        "error_details": "Container restart detected - monitoring lost during execution"
                    }
                )
                recovery_count += 1
                logger.info(f"Recovered orphaned request {request_id} (was '{old_state}')")
            except Exception as e:
                logger.error(f"Failed to recover request {request_id}: {e}")

        logger.info(f"Startup recovery complete: {recovery_count}/{len(orphaned_requests)} requests marked as failed")

    except Exception as e:
        logger.error(f"Error during orphaned request recovery: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _db_manager = MongoDBManager()
    await _db_manager.initialize_collections()

    # Recover orphaned requests from previous container instance
    await recover_orphaned_requests()

    # Config initialization - load from file (ConfigMap volume in K8s)
    config_manager = ConfigManager()
    await config_manager.sync_config()

    # Periodically reload config (picks up ConfigMap updates within ~60s)
    @repeat_every(seconds=60)
    async def sync_config():
        try:
            await config_manager.sync_config()
        except Exception as e:
            logger.error(f"Config sync failed: {e}")

    await sync_config()

    # Start scheduler leader election (handles sync_schedules automatically)
    await scheduler.start_leader_election()

    @repeat_every(seconds=60 * 60 * 24)  # Run once per day
    async def periodic_cleanup():
        try:
            success, msg = await request_tracker.cleanup_requests()
            if not success:
                logger.error(f"Request cleanup failed: {msg}")
            else:
                logger.info(msg)

            await log_persistence.enforce_retention()

            ag_cfg = config_manager.get_config("ai_governance") or {}
            if ag_cfg.get("enabled"):
                retention_days = int(ag_cfg.get("spend_logs_retention_days", 90))
                await ai_gateway_manager.purge_old_spend_logs(retention_days)
        except Exception as e:
            logger.error(f"Periodic cleanup failed: {e}")

    await periodic_cleanup()

    # Load cloud schema registry for Cloud Analyst
    schema_registry.load_schemas()

    # Periodically clean up idle analyst session pods (every 60s)
    @repeat_every(seconds=60)
    async def cleanup_analyst_sessions():
        try:
            await session_manager.cleanup_idle_sessions()
            await session_manager.pool_maintenance_loop()
        except Exception as e:
            logger.error(f"Analyst session cleanup failed: {e}")

    # Periodically clean up old analyst conversations (every 6 hours)
    @repeat_every(seconds=21600)
    async def cleanup_analyst_conversations():
        try:
            await chat_manager.cleanup_old_conversations()
        except Exception as e:
            logger.error(f"Analyst conversation cleanup failed: {e}")

    await cleanup_analyst_sessions()
    await cleanup_analyst_conversations()

    # Initialize the session pod pool (pre-warm pods for instant dispatch)
    await session_manager.start_pool()

    # Initialize runner pod pools (pre-warmed pods for IaC/discovery batch runs)
    await iac_pool_manager.start_pool()
    await discovery_pool_manager.start_pool()

    # Register pool managers for dynamic config changes (pool_size, execution_mode, etc.)
    ConfigManager.register_on_change(iac_pool_manager.on_config_change)
    ConfigManager.register_on_change(discovery_pool_manager.on_config_change)
    ConfigManager.register_on_change(session_manager.on_config_change)

    # Periodically maintain runner pools (every 30s)
    @repeat_every(seconds=30)
    async def runner_pool_maintenance():
        try:
            await iac_pool_manager.pool_maintenance_loop()
            await discovery_pool_manager.pool_maintenance_loop()
        except Exception as e:
            logger.error(f"Runner pool maintenance failed: {e}")

    await runner_pool_maintenance()

    # Approval timeout: auto-reject plans that have been awaiting approval too long
    @repeat_every(seconds=300)  # Every 5 minutes
    async def approval_timeout_check():
        try:
            from datetime import datetime, timedelta, timezone
            from app.database_generic_operator import MongoDBManager
            from app.managers.plan_store import PlanStore

            ag_cfg = config_manager.get_config("approval_gate") or {}
            timeout_hours = int(ag_cfg.get("timeout_hours", 48))
            cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

            _db_manager = MongoDBManager()
            planned = await _db_manager.find_documents(
                "requests",
                {"state": "planned"},
            )
            if not planned:
                return

            plan_store = PlanStore()
            expired = [
                r for r in planned
                if r.get("requested_on") and
                datetime.fromisoformat(r["requested_on"]).replace(tzinfo=timezone.utc) < cutoff
            ]

            for r in expired:
                request_id = r.get("request_id")
                p_name = r.get("project_name")
                w_name = r.get("workspace_name")
                try:
                    await _db_manager.update_document(
                        "requests",
                        {"request_id": request_id},
                        {"state": "approval_timed_out",
                         "error_details": f"Plan approval not received within {timeout_hours} hours"},
                    )
                    if p_name and w_name:
                        await project_manager.set_workspace_state(p_name, w_name, False)
                        from app.deps import queue_manager as _qm
                        await _qm.dequeue_next(p_name, w_name)
                    plan_store.delete_plan(request_id)
                    from app.routes.internal import _maybe_update_check_run
                    await _maybe_update_check_run(request_id, "approval_timed_out")
                    logger.info("Auto-rejected plan %s (approval timeout)", request_id)
                except Exception as exc:
                    logger.error("Failed to auto-reject plan %s: %s", request_id, exc)
        except Exception as e:
            logger.error(f"Approval timeout check failed: {e}")

    await approval_timeout_check()

    # Create default admin user on first boot
    success, _ = await project_manager.user_exists(master_admin)
    if not success:
        import secrets as _secrets
        first_boot_password = _secrets.token_urlsafe(16)
        success, msg = await project_manager.create_users(
            users=[
                {"username": master_admin, "password": first_boot_password, "org_roles": ["org_admin"]}
            ]
        )
        if success:
            _store_initial_admin_secret(first_boot_password)
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            logger.info("=" * 60)
            logger.info("  FIRST BOOT: Default admin user created")
            logger.info(f"  Username: {master_admin}")
            logger.info("  Retrieve password:")
            logger.info(f"    kubectl get secret qubiva-initial-admin-secret -n {namespace} \\")
            logger.info("      -o jsonpath='{{.data.password}}' | base64 -d")
            logger.info("  Please change this password after first login!")
            logger.info("=" * 60)
        else:
            logger.error(f"Failed to create admin user: {msg}")

    yield
    # Release scheduler leader lock so another pod can take over immediately
    try:
        await scheduler.stop_leader_election()
    except Exception as e:
        logger.warning(f"Failed to stop scheduler leader election: {e}")

    # Cleanup analyst session pods
    try:
        await session_manager.cleanup_all_sessions()
    except Exception as e:
        logger.warning(f"Failed to cleanup analyst sessions: {e}")

    # Cleanup runner pool pods
    try:
        await iac_pool_manager.cleanup_all()
        await discovery_pool_manager.cleanup_all()
    except Exception as e:
        logger.warning(f"Failed to cleanup runner pool pods: {e}")

    # Cleanup background clients
    try:
        await log_persistence.close()
    except Exception as e:
        logger.warning(f"Failed to close log persistence client: {e}")


# ---------------------------------------------------------------------------
# Create FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    lifespan=lifespan,
    debug=True,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,  # Disable automatic OpenAPI schema generation
)


# ---------------------------------------------------------------------------
# Static files and template globals
# ---------------------------------------------------------------------------

# Always mount static files from the container.
# In production K8s, an external CDN URL can be set via STATIC_CONTENT_URL
# to offload static asset serving (e.g. "https://cdn.example.com").
# When not set, assets are served directly by FastAPI from /static/.
app.mount("/static", StaticFiles(directory="static"), name="static")

# Update template globals with app base URL (deps.py sets it to "" initially)
templates.env.globals["app_base_url"] = get_app_base_url() or ""


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(status.HTTP_403_FORBIDDEN)
async def custom_403_handler(request: Request, exc: StarletteHTTPException):
    """
    Custom handler for 403 errors for paths starting with '/dashboard'
    """
    # Log the path that triggered the handler
    logger.debug(f"403 handler called for path: {request.url.path}")

    # Check if the URL path starts with '/dashboard'
    if request.url.path.startswith("/dashboard"):
        return templates.TemplateResponse(
            "dashboard_403.html",
            {
                "request": request,
                "message": "You don't have the required permissions to access this page or resource.",
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # For all other paths, return a standard FastAPI 404 response
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN, content={"message": "Access denied."}
    )


@app.exception_handler(status.HTTP_404_NOT_FOUND)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    """
    Custom handler for 404 errors for paths starting with '/dashboard'
    """

    # Check if the URL path starts with '/dashboard'
    if request.url.path.startswith("/dashboard"):
        logger.debug(f"404 handler called for path: {request.url.path}")
        return templates.TemplateResponse(
            "dashboard_404.html",
            {
                "request": request,
                "message": "The page or resource you are looking for does not exist.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # For all other paths, return a standard FastAPI 404 response
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"message": "Resource Not Found"}
    )


# ---------------------------------------------------------------------------
# Include all route modules
# ---------------------------------------------------------------------------

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(stats.router)
app.include_router(auth_routes.router)
app.include_router(org.router)
app.include_router(projects.router)
app.include_router(github.router)
app.include_router(cloud_accounts.router)
app.include_router(workspaces.router)
app.include_router(requests.router)
app.include_router(discovery.router)
app.include_router(tasks.router)
app.include_router(alerts.router)
app.include_router(sso.router)
app.include_router(analyst.router)
app.include_router(dashboard.router)
app.include_router(ai_governance.router)
app.include_router(project_tokens.router)
app.include_router(run_actions.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
