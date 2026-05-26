"""
Run approval and plan output routes for Terraform workspace runs.

Provides endpoints to:
- Fetch captured plan output for display in the UI
- Approve a plan (trigger apply phase)
- Reject a plan (cancel the run and release workspace lock)
"""

import logging
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.deps import (
    ConfigManager,
    log_persistence,
    project_manager,
    request_tracker,
    iac_pool_manager,
    queue_manager,
    get_request_tracker,
)
from app.auth_helpers import authenticate_http_user
from app.auth.cloud_auth import MultiCloudAuthentication
from app.request_manager import RequestTracker
from app.iac_executor import IaCJobTrigger

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


def _require_workspace_execute(user: dict, project_name: str):
    """Raise 403 if user lacks org_admin or project-level workspace execute permission."""
    org_roles = user.get("org_roles", [])
    if "org_admin" in org_roles:
        return
    project_roles = user.get("project_roles", {}).get(project_name, [])
    if "project_admin" in project_roles or "project_workspace_execute" in project_roles:
        return
    raise HTTPException(status_code=403, detail="Insufficient permissions to approve or reject plans")


@router.get("/api/v1/projects/{project_name}/workspaces/{workspace_name}/runs/{request_id}/plan")
async def get_plan_output(
    project_name: str,
    workspace_name: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    tracker: RequestTracker = Depends(get_request_tracker),
):
    """Return the captured terraform plan output for a run awaiting approval."""
    success, details = await tracker.get_request_details(request_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Run {request_id} not found")

    if details.get("project_name") != project_name or details.get("workspace_name") != workspace_name:
        raise HTTPException(status_code=404, detail="Run not found in this workspace")

    return {
        "request_id": request_id,
        "state": details.get("state"),
        "plan_output": details.get("plan_output", ""),
        "approved_by": details.get("approved_by"),
        "approved_at": details.get("approved_at"),
    }


@router.post("/api/v1/projects/{project_name}/workspaces/{workspace_name}/runs/{request_id}/approve")
async def approve_plan(
    project_name: str,
    workspace_name: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    tracker: RequestTracker = Depends(get_request_tracker),
):
    """Approve a plan and trigger the apply phase using the saved plan binary."""
    _require_workspace_execute(user, project_name)

    # Verify the run is in "planned" state
    success, details = await tracker.get_request_details(request_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Run {request_id} not found")
    if details.get("project_name") != project_name or details.get("workspace_name") != workspace_name:
        raise HTTPException(status_code=404, detail="Run not found in this workspace")
    if details.get("state") != "planned":
        raise HTTPException(
            status_code=400,
            detail=f"Run is in state '{details.get('state')}', not 'planned'. Only planned runs can be approved.",
        )

    # Record approval metadata
    username = user.get("username", "unknown")
    approved_at = datetime.now(timezone.utc).isoformat()
    await tracker.update_request_fields(request_id, {
        "approved_by": username,
        "approved_at": approved_at,
    })

    # Re-fetch workspace + cloud credentials to trigger apply
    try:
        run_success, run_details = await project_manager.get_terraform_run_details(
            project_name=project_name,
            workspace_name=workspace_name,
        )
        if not run_success:
            raise HTTPException(status_code=400, detail=f"Failed to load workspace config: {run_details}")

        # Get GitHub token
        if run_details.get("github_repo", {}).get("repo_url"):
            try:
                github_token, auth_type = await project_manager.get_github_token_for_container_run(
                    repo_url=run_details["github_repo"]["repo_url"],
                    repo_details=run_details["github_repo"],
                )
                run_details["github_repo"]["token"] = github_token
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to get GitHub token: {exc}")

        # Get cloud auth
        try:
            cloudauth = MultiCloudAuthentication(
                cloud_platform=run_details["cloud_platform"],
                project_manager=project_manager,
                project_name=project_name,
                account_id=run_details["cloud_account"],
            )
            await cloudauth.initialize()
            run_details["auth_env_vars"] = await cloudauth.get_auth_env_vars()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to authenticate with cloud provider: {exc}")

        # Create IaCJobTrigger reusing the same request_id
        iac_trigger = IaCJobTrigger(
            request_tracker,
            request_id,
            project_manager,
            log_persistence=log_persistence,
            pool_manager=iac_pool_manager,
            config_manager=ConfigManager,
            queue_manager=queue_manager,
        )

        # Trigger apply phase — plan_request_id signals the executor to skip lock
        # acquisition and pass TF_PLAN_REQUEST_ID to the runner
        result = await iac_trigger.trigger_terraform_command(
            project_name=project_name,
            workspace_name=workspace_name,
            run_details=run_details,
            phases=["apply"],
            request_id=request_id,
            plan_request_id=request_id,
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Apply trigger failed"))

        return {
            "status": "success",
            "message": "Plan approved — apply phase started",
            "request_id": request_id,
            "approved_by": username,
            "approved_at": approved_at,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error triggering apply after approval for %s: %s", request_id, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to trigger apply: {exc}")


@router.post("/api/v1/projects/{project_name}/workspaces/{workspace_name}/runs/{request_id}/reject")
async def reject_plan(
    project_name: str,
    workspace_name: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    tracker: RequestTracker = Depends(get_request_tracker),
):
    """Reject a plan, cancel the run, and release the workspace lock."""
    _require_workspace_execute(user, project_name)

    success, details = await tracker.get_request_details(request_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Run {request_id} not found")
    if details.get("project_name") != project_name or details.get("workspace_name") != workspace_name:
        raise HTTPException(status_code=404, detail="Run not found in this workspace")
    if details.get("state") != "planned":
        raise HTTPException(
            status_code=400,
            detail=f"Run is in state '{details.get('state')}', not 'planned'. Only planned runs can be rejected.",
        )

    username = user.get("username", "unknown")

    # Mark as rejected
    await tracker.update_request_fields(request_id, {"rejected_by": username})
    await tracker.update_request_state(request_id, "rejected")

    # Release workspace lock so other runs can proceed
    await project_manager.set_workspace_state(project_name, workspace_name, False)

    # Trigger next queued run (if any) now that the workspace is free
    import asyncio
    asyncio.create_task(queue_manager.dequeue_next(project_name, workspace_name))

    # Update GitHub Check Run (fire-and-forget)
    from app.routes.internal import _maybe_update_check_run
    asyncio.create_task(_maybe_update_check_run(request_id, "rejected"))

    # Clean up the plan binary artifact
    try:
        from app.managers.plan_store import PlanStore
        PlanStore().delete_plan(request_id)
    except Exception as exc:
        logger.debug("Plan artifact cleanup failed for %s: %s", request_id, exc)

    return {
        "status": "success",
        "message": "Plan rejected — workspace unlocked",
        "request_id": request_id,
        "rejected_by": username,
    }


@router.post("/api/v1/projects/{project_name}/workspaces/{workspace_name}/runs/{request_id}/cancel")
async def cancel_queued_run(
    project_name: str,
    workspace_name: str,
    request_id: str,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    """Cancel a queued run before it starts."""
    _require_workspace_execute(user, project_name)

    doc = await tracker.db_manager.find_document("requests", {"request_id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    if doc.get("state") != "queued":
        raise HTTPException(status_code=400, detail=f"Run is not queued (state: {doc.get('state')})")

    await tracker.update_request_state(request_id, "cancelled")

    return {
        "status": "success",
        "message": "Queued run cancelled",
        "request_id": request_id,
    }
