"""
Workspace management and Terraform execution routes for Qubiva.
"""

import logging
import traceback
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.deps import (
    ConfigManager,
    audit_logger,
    log_persistence,
    project_manager,
    request_tracker,
    iac_pool_manager,
    queue_manager,
    get_request_tracker,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.auth.cloud_auth import MultiCloudAuthentication
from app.decorators import permissions, track_request
from app.request_manager import RequestTracker
from app.iac_executor import IaCJobTrigger

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/api/v1/projects/{project_name}/workspaces")
@permissions(["project_get"])
async def get_project_workspaces(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, workspaces = await project_manager.list_workspaces(project_name)
    if success:
        return workspaces
    else:
        raise HTTPException(status_code=404, detail=workspaces)


@router.post("/api/v1/projects/{project_name}/workspaces/create")
@permissions(["project_workspace_create"])
async def api_create_workspace(
    project_name: str,
    workspace_data: Models.CreateWorkspaceModel,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.create_workspace(
        project_name,
        workspace_data.name,
        workspace_data.description,
        workspace_data.variables,
        workspace_data.secrets,
        workspace_data.terraform_version,
        workspace_data.github_repo_name,
        workspace_data.cloud_account,
        workspace_data.cloud_platform,
        trigger_branch=workspace_data.trigger_branch,
        acting_user=username,
    )

    if success:
        await audit_logger.log_event("create_workspace", username, "workspace", workspace_data.name, project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.get("/api/v1/projects/{project_name}/workspaces/{workspace_name}")
@permissions(["project_workspace_get"])
async def get_workspace_details(
    project_name: str,
    workspace_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, workspace_details = await project_manager.get_workspace_details(
        project_name, workspace_name
    )
    if success:
        logger.debug("howdy")
        logger.debug(workspace_details)
        return workspace_details
    else:
        raise HTTPException(status_code=404, detail=workspace_details)


@router.put("/api/v1/projects/{project_name}/workspaces/{workspace_name}/edit")
@permissions(["project_workspace_edit"])
async def api_update_workspace(
    project_name: str,
    workspace_name: str,
    workspace_data: Models.UpdateWorkspaceModel,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.update_workspace(
        project_name,
        workspace_name,
        workspace_data.description,
        workspace_data.variables,
        workspace_data.secrets,
        workspace_data.terraform_version,
        workspace_data.github_repo_name,
        workspace_data.cloud_account,
        workspace_data.cloud_platform,
        trigger_branch=workspace_data.trigger_branch,
        acting_user=username,
    )

    if success:
        await audit_logger.log_event("update_workspace", username, "workspace", workspace_name, project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.delete("/api/v1/projects/{project_name}/workspaces/{workspace_name}/delete")
@permissions(["project_workspace_delete"])
async def delete_workspace_from_project(
    project_name: str,
    workspace_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.delete_workspace_from_project(
        project_name, workspace_name, acting_user=username
    )
    if success:
        await audit_logger.log_event("delete_workspace", username, "workspace", workspace_name, project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=404, detail=response)


@router.post("/api/v1/projects/{project_name}/workspaces/{workspace_name}/execute")
@permissions(["project_workspace_execute"])
@track_request(
    "terraform_run",
    additional_details_func=lambda inputs: {
        "project_name": inputs.get("project_name"),
        "workspace_name": inputs.get("workspace_name"),
        "phases": getattr(inputs.get("payload"), "phases", []) if inputs.get("payload") else [],
        "requested_by_user": inputs.get("user", {}).get("username") if inputs.get("user") else "unknown"
    },
)
async def execute_terraform(
    request: Request,
    project_name: str,
    workspace_name: str,
    payload: Models.TerraformExecutePayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    tracker: RequestTracker = Depends(get_request_tracker),
    request_id: str = None,
):
    try:
        # Initialize IaC job trigger
        try:
            iac_trigger = IaCJobTrigger(
                request_tracker,
                request_id,
                project_manager,
                log_persistence=log_persistence,
                pool_manager=iac_pool_manager,
                config_manager=ConfigManager,
                queue_manager=queue_manager,
            )
        except Exception as e:
            error_msg = f"Failed to set up IaC execution environment: {str(e)}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            logger.error(f"Error initializing IaCJobTrigger: {e}")
            raise HTTPException(
                status_code=500,
                detail=error_msg,
            )

        success, run_details = await project_manager.get_terraform_run_details(
            project_name=project_name,
            workspace_name=workspace_name
        )
        if not success:
            error_msg = f"Failed to retrieve Terraform configuration: {run_details}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=error_msg)

        if not run_details["github_repo"].get("terraform_config_path"):
            error_msg = "Terraform configuration path not specified in repository settings"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=error_msg)

        if run_details.get("github_repo") and run_details["github_repo"].get("repo_url"):
            try:
                github_token, auth_type = await project_manager.get_github_token_for_container_run(
                    repo_url=run_details["github_repo"]["repo_url"],
                    repo_details=run_details["github_repo"]
                )
                run_details["github_repo"]["token"] = github_token
                logger.info(f"Using {auth_type} authentication for Terraform execution on {run_details['github_repo']['repo_url']}")
            except Exception as e:
                error_msg = f"Failed to get GitHub authentication: {str(e)}"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=500, detail=error_msg)

        # Get authentication variables
        try:
            cloudauth = MultiCloudAuthentication(
                cloud_platform=run_details["cloud_platform"],
                project_manager=project_manager,
                project_name=project_name,
               account_id=run_details["cloud_account"],
            )
            await cloudauth.initialize()
            auth_env_vars = await cloudauth.get_auth_env_vars()
            run_details["auth_env_vars"] = auth_env_vars
        except Exception as e:
            error_msg = f"Failed to authenticate with cloud provider: {str(e)}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=500, detail=error_msg)

        logger.debug("final run details before triggering terraform")
        logger.debug(run_details)
        # Trigger IaC command
        try:
            result = await iac_trigger.trigger_terraform_command(
                project_name=project_name,
                workspace_name=workspace_name,
                run_details=run_details,
                phases=payload.phases,
                request_id=request_id,
                timeout_hours=payload.task_timeout_hours,
            )
        except Exception as e:
            error_msg = f"Failed to start Terraform execution: {str(e)}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            logger.error(f"Error executing Terraform job: {e}")
            raise HTTPException(status_code=500, detail=error_msg)

        # Handle errors from the terraform command execution
        if result["status"] == "error":
            error_msg = f"Terraform execution failed during startup: {result['error']}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=error_msg)

        # Workspace busy — run queued, will start when workspace becomes available
        if result["status"] == "queued":
            return {
                "status": "queued",
                "message": f"Workspace is busy. Run queued at position {result.get('queue_position', '?')}.",
                "request_id": request_id,
                "queue_position": result.get("queue_position"),
            }

        # Execution started — update tracker to 'in progress'
        await tracker.update_request_state(request_id, "in progress")
        return {
            "status": "success",
            "message": "Terraform execution started successfully",
            "task_arn": result["task_arn"],
            "request_id": request_id,
        }
    except HTTPException:
        # Re-raise HTTP exceptions without modification
        raise
    except Exception as e:
        # Handle any unexpected errors
        error_msg = "An unexpected error occurred during Terraform execution setup"
        await tracker.update_error_details(request_id, f"{error_msg}: {str(e)}")
        await tracker.update_request_state(request_id, "failed")
        logger.error(f"Unexpected error in execute_terraform: {e}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/api/v1/projects/{project_name}/workspaces/{workspace_name}/runs")
async def get_terraform_runs(
    project_name: str,
    workspace_name: str,
    page: int = 1,
    page_size: int = 10,
    user: dict = Depends(authenticate_http_user),
    tracker: RequestTracker = Depends(get_request_tracker),
):
    try:
        custom_filter = {"workspace_name": workspace_name}
        success, result = await tracker.list_requests(
            project_name, "terraform_run", page, page_size, custom_filter=custom_filter
        )
        if not success:
            raise HTTPException(status_code=500, detail=result)

        # Format the runs data
        formatted_runs = []
        for run in result["runs"]:
            logger.debug("run data")
            logger.debug(run)
            formatted_run = {
                "request_id": run.get(
                    "request_id", ""
                ),  # Assuming we've added this in the RequestTracker
                "requested_by": run["requested_by"],
                "requested_on": run["requested_on"],
                "state": run["state"],
                # Add these if they exist in your data, otherwise they'll be 'N/A' in the frontend
                "cloud_account": run.get("cloud_account", "N/A"),
                "github_repo": run.get("github_repo", "N/A"),
                "phases": run.get("phases", ["N/A"]),
                "trigger_source": run.get("trigger_source", "manual"),
                "is_speculative": run.get("is_speculative", False),
                "pr_number": run.get("pr_number"),
                "head_sha": run.get("head_sha", ""),
            }
            formatted_runs.append(formatted_run)
        logger.debug("deepak")
        logger.debug(formatted_runs)
        return {
            "runs": formatted_runs,
            "total_pages": result["total_pages"],
            "current_page": result["page"],
            "page_size": result["page_size"],
        }
    except Exception as e:
        logger.debug(f"Exception occurred: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/projects/{project_name}/workspaces/{workspace_name}/lock-status")
@permissions(["project_workspace_get"])
async def get_workspace_lock_status(
    project_name: str,
    workspace_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Get current lock status of workspace"""
    try:
        is_locked, current_run_id = await project_manager.is_workspace_locked(project_name, workspace_name)

        # If locked, get request details
        request_details = None
        if is_locked and current_run_id:
            success, details = await request_tracker.get_request_details(current_run_id)
            if success:
                state = details.get('state')
                # Stale lock: the run that held the lock has already finished.
                # Clear it now and report the workspace as available so the UI
                # never shows "Locked by completed run".
                if state in RequestTracker.TERMINAL_STATES:
                    await project_manager.set_workspace_state(project_name, workspace_name, False)
                    return {
                        "is_locked": False,
                        "current_run_request_id": None,
                        "request_details": None,
                    }
                request_details = {
                    'request_id': current_run_id,
                    'state': state,
                    'requested_by': details.get('requested_by'),
                    'requested_on': details.get('requested_on')
                }

        return {
            "is_locked": is_locked,
            "current_run_request_id": current_run_id,
            "request_details": request_details
        }
    except Exception as e:
        logger.error(f"Error getting workspace lock status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get workspace lock status")


@router.post("/api/v1/projects/{project_name}/workspaces/{workspace_name}/force-unlock")
@permissions(["project_workspace_execute"])  # You can change this to a more restrictive role
async def force_unlock_workspace(
    project_name: str,
    workspace_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Force unlock workspace (admin operation)"""
    try:
        # Get current lock status first
        is_locked, current_run_id = await project_manager.is_workspace_locked(project_name, workspace_name)

        if not is_locked:
            return {"message": "Workspace is not currently locked"}

        # Force unlock
        success, message = await project_manager.set_workspace_state(project_name, workspace_name, False)

        if success:
            logger.info(f"Workspace {project_name}/{workspace_name} force unlocked by {user['username']}")
            return {
                "message": "Workspace force unlocked successfully",
                "previous_lock_request_id": current_run_id
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to unlock workspace: {message}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error force unlocking workspace: {e}")
        raise HTTPException(status_code=500, detail="Failed to force unlock workspace")
