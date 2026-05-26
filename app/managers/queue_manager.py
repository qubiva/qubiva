"""
Workspace-level run queue for IaC executor.

When a workspace is locked (a run is active or awaiting approval), new runs
are enqueued instead of rejected.  Once the workspace lock is released, the
oldest queued run is automatically dequeued and execution is started.

Queue storage is the existing MongoDB `requests` collection — no new
collection is needed.  Queued requests already carry all the context fields
set by the @track_request decorator (project_name, workspace_name, phases).
"""
import logging

logger = logging.getLogger("uvicorn.error")


class QueueManager:
    """Manage the per-workspace FIFO queue of pending IaC runs."""

    COLLECTION = "requests"

    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def _max_queue_depth(self) -> int:
        pools_cfg = self.config_manager.get_config("runner_pools") or {}
        return int(pools_cfg.get("max_queue_depth", 5))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def count_queued(self, project_name: str, workspace_name: str) -> int:
        """Return the number of runs currently queued for a workspace."""
        docs = await self.db_manager.find_documents(
            self.COLLECTION,
            {
                "state": "queued",
                "project_name": project_name,
                "workspace_name": workspace_name,
            },
        )
        return len(docs) if docs else 0

    async def is_queue_full(self, project_name: str, workspace_name: str) -> bool:
        depth = self._max_queue_depth()
        if depth <= 0:
            return False
        count = await self.count_queued(project_name, workspace_name)
        return count >= depth

    async def cancel_queued(self, request_id: str) -> bool:
        """Cancel a queued run (state → 'cancelled')."""
        try:
            await self.db_manager.update_document(
                self.COLLECTION,
                {"request_id": request_id, "state": "queued"},
                {"state": "cancelled"},
            )
            return True
        except Exception as exc:
            logger.error("QueueManager.cancel_queued failed for %s: %s", request_id, exc)
            return False

    async def dequeue_next(self, project_name: str, workspace_name: str) -> bool:
        """Find the oldest queued run for this workspace and start it.

        Re-fetches workspace config (credentials, GitHub token) fresh at
        dequeue time so nothing stale is used.

        Returns True if a run was dequeued and started, False otherwise.
        """
        # Late imports to avoid circular dependencies at module load time
        from app.deps import (
            project_manager,
            request_tracker,
            log_persistence,
            iac_pool_manager,
        )
        from app.app_config_manager import ConfigManager
        from app.iac_executor import IaCJobTrigger
        from app.auth.cloud_auth import MultiCloudAuthentication

        # Find oldest queued request for this workspace
        docs = await self.db_manager.find_documents(
            self.COLLECTION,
            {
                "state": "queued",
                "project_name": project_name,
                "workspace_name": workspace_name,
            },
        )
        if not docs:
            return False

        # Sort by requested_on ascending (oldest first)
        docs.sort(key=lambda d: d.get("requested_on", ""))
        next_doc = docs[0]
        request_id = next_doc["request_id"]
        phases = next_doc.get("phases") or ["init", "plan", "apply"]
        timeout_hours = next_doc.get("task_timeout_hours")

        logger.info(
            "Dequeuing request %s for %s/%s (phases=%s)",
            request_id, project_name, workspace_name, phases,
        )

        # Re-fetch workspace config (credentials must be fresh)
        try:
            success, run_details = await project_manager.get_terraform_run_details(
                project_name=project_name,
                workspace_name=workspace_name,
            )
            if not success:
                logger.error("Dequeue: failed to fetch run details for %s/%s: %s", project_name, workspace_name, run_details)
                await request_tracker.update_request_state(request_id, "failed")
                await request_tracker.update_error_details(request_id, f"Dequeue failed: {run_details}")
                return False

            # GitHub token
            if run_details.get("github_repo") and run_details["github_repo"].get("repo_url"):
                github_token, _ = await project_manager.get_github_token_for_container_run(
                    repo_url=run_details["github_repo"]["repo_url"],
                    repo_details=run_details["github_repo"],
                )
                run_details["github_repo"]["token"] = github_token

            # Cloud credentials
            cloudauth = MultiCloudAuthentication(
                cloud_platform=run_details["cloud_platform"],
                project_manager=project_manager,
                project_name=project_name,
                account_id=run_details["cloud_account"],
            )
            await cloudauth.initialize()
            run_details["auth_env_vars"] = await cloudauth.get_auth_env_vars()

        except Exception as exc:
            logger.error("Dequeue: error building run details for %s: %s", request_id, exc)
            await request_tracker.update_request_state(request_id, "failed")
            await request_tracker.update_error_details(request_id, f"Dequeue config error: {exc}")
            return False

        # Create executor and trigger (workspace lock will be acquired inside)
        try:
            iac_trigger = IaCJobTrigger(
                request_tracker=request_tracker,
                request_id=request_id,
                project_manager=project_manager,
                log_persistence=log_persistence,
                pool_manager=iac_pool_manager,
                config_manager=ConfigManager,
            )
            result = await iac_trigger.trigger_terraform_command(
                project_name=project_name,
                workspace_name=workspace_name,
                run_details=run_details,
                phases=phases,
                request_id=request_id,
                timeout_hours=timeout_hours,
            )
            if result.get("status") == "error":
                logger.error("Dequeue: trigger_terraform_command error for %s: %s", request_id, result.get("error"))
                return False
            if result.get("status") == "queued":
                # Workspace became busy again between dequeue checks — already re-queued
                logger.info("Dequeue: workspace busy again, request %s re-queued", request_id)
                return False

            logger.info("Dequeued and started request %s", request_id)
            return True

        except Exception as exc:
            logger.error("Dequeue: execution error for %s: %s", request_id, exc)
            await request_tracker.update_request_state(request_id, "failed")
            await request_tracker.update_error_details(request_id, f"Dequeue execution error: {exc}")
            return False
