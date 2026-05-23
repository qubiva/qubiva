"""
Cloud query execution, discovery, and benchmark routes for Qubiva.
"""

import os
import json
import logging
import traceback
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.deps import (
    ConfigManager,
    discovery_manager,
    discovery_dashboard,
    log_persistence,
    project_manager,
    request_tracker,
    discovery_pool_manager,
    get_request_tracker,
    get_scheduler,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.auth.cloud_auth import MultiCloudAuthentication
from app.decorators import permissions, track_request, schedulable_endpoint, validate_resource
from app.request_manager import RequestTracker
from app.discovery_executor import DiscoveryJobTrigger
from app.discovery_analyzer import DiscoveryAnalyzer
from app.chart_data_builder import ChartDataBuilder
from app.scheduler import Scheduler

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/api/v1/discovery/benchmarks/{cloud_platform}/{mod_type}")
async def get_available_benchmarks(
    cloud_platform: str,
    mod_type: str,
    user: dict = Depends(authenticate_http_user),
):
    """Get available benchmarks for a given cloud platform and mod type"""
    try:
        mods_config = ConfigManager.get_config('compliance_mods')

        if not mods_config:
            raise HTTPException(status_code=500, detail="Compliance mods configuration not found")

        cloud_platform_lower = cloud_platform.lower()
        if cloud_platform_lower not in mods_config:
            raise HTTPException(status_code=404, detail=f"No mods configured for platform: {cloud_platform}")

        if mod_type not in mods_config[cloud_platform_lower]:
            raise HTTPException(status_code=404, detail=f"Mod type '{mod_type}' not found for platform: {cloud_platform}")

        mod_config = mods_config[cloud_platform_lower][mod_type]

        return {
            "cloud_platform": cloud_platform,
            "mod_type": mod_type,
            "benchmarks": mod_config['benchmarks']
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching benchmarks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/runs"
)
async def get_cloud_query_runs(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    page: int = 1,
    page_size: int = 10,
    user: dict = Depends(authenticate_http_user),
    tracker: RequestTracker = Depends(get_request_tracker),
):
    try:
        custom_filter = {"cloud_account": account_id, "cloud_platform": cloud_platform}

        # Pass BOTH request types as a list
        success, result = await tracker.list_requests(
            project_name,
            ["query_run", "discovery_run"],  # LIST of types
            page,
            page_size,
            custom_filter=custom_filter
        )

        if not success:
            raise HTTPException(status_code=500, detail=result)

        # Format the runs data
        formatted_runs = []
        for run in result["runs"]:
            formatted_run = {
                "request_id": run.get("request_id", ""),
                "requested_by": run["requested_by"],
                "requested_on": run["requested_on"],
                "state": run["state"],
                "cloud_account": run.get("cloud_account", "N/A"),
                "request_type": run.get("request_type", "N/A"),  # ADD THIS
                "run_type": run.get("run_type", "N/A"),
                "git_repo": run.get("git_repo", "N/A"),
                "use_auto_benchmark": run.get("use_auto_benchmark", False),
                "mod_type": run.get("mod_type"),
                "benchmark_id": run.get("benchmark_id"),
            }
            formatted_runs.append(formatted_run)

        return {
            "runs": formatted_runs,
            "total_pages": result["total_pages"],
            "current_page": result["page"],
            "page_size": result["page_size"],
        }
    except Exception as e:
        logger.debug(f"Exception occurred: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/run_query"
)
@schedulable_endpoint()
@track_request(
    "query_run",
    additional_details_func=lambda inputs: {
        "cloud_account": inputs.get("account_id"),
        "cloud_platform": inputs.get("cloud_platform"),
        "project_name": inputs.get("project_name"),
        "run_type": getattr(inputs.get("payload"), "run_type", None),
        "git_repo": getattr(inputs.get("payload"), "git_repo", None),
        "use_auto_benchmark": getattr(
            inputs.get("payload"), "use_auto_benchmark", None
        ),
        "mod_type": getattr(inputs.get("payload"), "mod_type", None),
        "benchmark_id": getattr(inputs.get("payload"), "benchmark_id", None),
        "query_engine_version": getattr(
            inputs.get("payload"), "query_engine_version", "latest"
        ),
        "compliance_engine_version": getattr(
            inputs.get("payload"), "compliance_engine_version", "latest"
        ),
        "plugin_version": getattr(inputs.get("payload"), "plugin_version", "latest"),
    },
)
async def execute_cloud_query(
    request: Request,
    project_name: str,
    cloud_platform: str,
    account_id: str,
    payload: Models.QueryTriggerPayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    tracker: RequestTracker = Depends(get_request_tracker),
    request_id: str = None,
):
    try:
        # Get version defaults from config
        query_engine_version = ConfigManager.get_config('query_engine_versions', 'query_engine_version') or payload.query_engine_version
        compliance_engine_version = ConfigManager.get_config('query_engine_versions', 'compliance_engine_version') or payload.compliance_engine_version
        plugin_version = ConfigManager.get_config('query_engine_versions', 'plugin_versions', cloud_platform) or payload.plugin_version

        # Initialize the discovery trigger
        try:
            discovery_trigger = DiscoveryJobTrigger(
                tracker,
                request_id,
                ConfigManager,
                log_persistence=log_persistence,
                pool_manager=discovery_pool_manager,
            )
        except Exception as e:
            error_msg = f"Failed to initialize discovery job trigger: {str(e)}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            logger.error(f"Error initializing DiscoveryJobTrigger: {e}")
            raise HTTPException(status_code=500, detail=error_msg)

        # Get authentication environment variables
        try:
            cloudauth = MultiCloudAuthentication(
                cloud_platform=cloud_platform,
                project_manager=project_manager,
                project_name=project_name,
                account_id=account_id,
            )
            await cloudauth.initialize()
            auth_env_vars = await cloudauth.get_auth_env_vars()
            logger.debug("printing auth env vars")
            logger.debug(auth_env_vars)
        except Exception as e:
            error_msg = f"Failed to authenticate with cloud provider: {str(e)}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=500, detail=error_msg)

        # Prepare run details
        run_details = {
            "auth_env_vars": auth_env_vars,
        }

        # Handle GitHub repository details if provided
        github_repo = None
        mod_github_url = None
        mod_name = None

        if payload.run_type == 'benchmark' and payload.use_auto_benchmark:
            # Get mod configuration
            mods_config = ConfigManager.get_config('compliance_mods')

            if not mods_config:
                error_msg = "Compliance mods configuration not found"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=500, detail=error_msg)

            cloud_platform_lower = cloud_platform.lower()

            if cloud_platform_lower not in mods_config:
                error_msg = f"No mods configured for cloud platform: {cloud_platform}"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=400, detail=error_msg)

            if payload.mod_type not in mods_config[cloud_platform_lower]:
                error_msg = f"Invalid mod_type '{payload.mod_type}' for platform '{cloud_platform}'"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=400, detail=error_msg)

            mod_config = mods_config[cloud_platform_lower][payload.mod_type]

            # Validate benchmark_id exists in the config
            valid_benchmark_ids = [b['id'] for b in mod_config['benchmarks']]
            if payload.benchmark_id not in valid_benchmark_ids:
                error_msg = f"Invalid benchmark_id '{payload.benchmark_id}'. Available: {', '.join(valid_benchmark_ids)}"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=400, detail=error_msg)

            mod_github_url = mod_config['github_url']
            mod_name = mod_config['mod_name']

        elif payload.git_repo:
            try:
                github_repo_name_items = payload.git_repo.rsplit("/", 2)
                github_repo_name = (
                    f"{github_repo_name_items[-2]}~{github_repo_name_items[-1]}".replace(
                        ".git", ""
                    )
                )
            except Exception:
                error_msg = "Invalid GitHub repository URL format"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=400, detail=error_msg)

            success, repo_details = await project_manager.get_github_repo_details(
                project_name, github_repo_name
            )
            if not success:
                error_msg = f"Failed to fetch GitHub repository details: {repo_details}"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=400, detail=error_msg)

            if not repo_details.get("discovery_queries_path"):
                error_msg = "Discovery queries path is not configured in the repository settings"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=400, detail=error_msg)

            github_repo = {
                "repo_url": repo_details.get("repo_url"),
                "branch": repo_details.get("branch"),
                "discovery_queries_path": repo_details.get("discovery_queries_path"),
                "custom_benchmark_path": repo_details.get("custom_benchmark_path"),
                "token": repo_details.get("token"),
            }

            try:
                github_token, auth_type = await project_manager.get_github_token_for_container_run(
                    repo_url=github_repo["repo_url"],
                    repo_details=github_repo
                )
                github_repo["token"] = github_token
                logger.info(f"Using {auth_type} authentication for discovery execution on {github_repo['repo_url']}")
            except Exception as e:
                error_msg = f"Failed to get GitHub authentication: {str(e)}"
                await tracker.update_error_details(request_id, error_msg)
                await tracker.update_request_state(request_id, "failed")
                raise HTTPException(status_code=500, detail=error_msg)

            # Validate GitHub repository paths based on run_type and use_auto_benchmark
            if payload.run_type == "benchmark" and not payload.use_auto_benchmark:
                if not github_repo["custom_benchmark_path"]:
                    error_msg = "Custom benchmark path is not configured in the repository settings"
                    await tracker.update_error_details(request_id, error_msg)
                    await tracker.update_request_state(request_id, "failed")
                    raise HTTPException(
                        status_code=422,
                        detail="The selected Git repository does not have `custom_benchmark_path` configured. Update this Git repository with `custom_benchmark_path` to run a custom benchmark check.",
                    )
            elif payload.run_type == "query":
                if not github_repo["discovery_queries_path"]:
                    error_msg = "Discovery queries path is not configured in the repository settings"
                    await tracker.update_error_details(request_id, error_msg)
                    await tracker.update_request_state(request_id, "failed")
                    raise HTTPException(
                        status_code=422,
                        detail="The selected Git repository does not have `discovery_queries_path` configured. Update this Git repository with `discovery_queries_path` to run the query.",
                    )

        # Trigger the discovery command
        try:
            result = await discovery_trigger.trigger_discovery_command(
                project_name=project_name,
                run_details=run_details,
                run_type=payload.run_type,
                request_id=request_id,
                cloud_platform=cloud_platform,
                query_engine_version=query_engine_version,
                compliance_engine_version=compliance_engine_version,
                plugin_version=plugin_version,
                github_repo=github_repo,
                use_auto_benchmark=payload.use_auto_benchmark,
                timeout_hours=payload.task_timeout_hours,
                mod_type=payload.mod_type,
                benchmark_id=payload.benchmark_id,
                mod_github_url=mod_github_url,
                mod_name=mod_name,
            )
        except Exception as e:
            error_msg = f"Failed to execute discovery command: {str(e)}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            logger.error(f"Error executing discovery job: {e}")
            raise HTTPException(status_code=500, detail=error_msg)

        # Handle errors from the discovery command execution
        if result["status"] == "error":
            error_msg = f"Job trigger failed: {result['error']}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=error_msg)

        # Return success response
        await tracker.update_request_state(request_id, "in progress")
        return {
            "status": "success",
            "message": "Job triggered successfully.",
            "task_arn": result["task_arn"],
            "request_id": request_id,
        }

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Handle unexpected errors
        error_msg = f"An unexpected error occurred: {str(e)}"
        await tracker.update_error_details(request_id, error_msg)
        await tracker.update_request_state(request_id, "failed")
        logger.error(f"Unexpected error in execute_cloud_query: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/api/v1/discovery/resource_types/{cloud_platform}")
@permissions([])
async def get_available_resource_types(
    cloud_platform: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """
    Get available resource types for a cloud platform from config.
    Returns list of {table_name, description} for UI selection.
    """
    try:
        resource_types_dict = discovery_manager.get_available_resource_types(cloud_platform)

        if not resource_types_dict:
            raise HTTPException(
                status_code=404,
                detail=f"No resource types found for platform: {cloud_platform}"
            )

        # Convert to list format for frontend
        resource_types_list = [
            {"table_name": table_name, "description": description}
            for table_name, description in resource_types_dict.items()
        ]

        return {
            "cloud_platform": cloud_platform,
            "resource_types": resource_types_list
        }

    except Exception as e:
        logger.error(f"Failed to get resource types: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/discovery/config")
@permissions(["project_cloud_account_get"])
async def get_discovery_config(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """
    Get discovery configuration (selected resource types) for a cloud account.
    Returns empty list if not configured yet.
    """
    try:
        selected_types = await discovery_manager.get_selected_resource_types(
            project_name,
            cloud_platform,
            account_id
        )

        # Get available types with descriptions
        available_types = discovery_manager.get_available_resource_types(cloud_platform)

        # Build response with descriptions for selected types
        if selected_types:
            selected_with_descriptions = [
                {
                    "table_name": table_name,
                    "description": available_types.get(table_name, "Unknown")
                }
                for table_name in selected_types
            ]
        else:
            selected_with_descriptions = []

        return {
            "project_name": project_name,
            "cloud_platform": cloud_platform,
            "account_id": account_id,
            "is_configured": selected_types is not None,
            "selected_resource_types": selected_with_descriptions
        }

    except Exception as e:
        logger.error(f"Failed to get discovery config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/discovery/config")
@permissions(["project_cloud_account_edit"])
async def update_discovery_config(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    config_update: Models.DiscoveryConfigUpdate,  # You'll need to add this model
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """
    Update discovery configuration (selected resource types) for a cloud account.
    """
    try:
        success, message = await discovery_manager.save_selected_resource_types(
            project_name,
            cloud_platform,
            account_id,
            config_update.selected_resource_types
        )

        if success:
            return {"message": message}
        else:
            raise HTTPException(status_code=400, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update discovery config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/run_discovery")
@schedulable_endpoint()
@track_request(
    "discovery_run",
    additional_details_func=lambda inputs: {
        "cloud_account": inputs.get("account_id"),
        "cloud_platform": inputs.get("cloud_platform"),
        "project_name": inputs.get("project_name"),
    }
)
@permissions(["project_cloud_account_get"])
async def trigger_discovery(
    request: Request,
    project_name: str,
    cloud_platform: str,
    account_id: str,
    payload: Models.DiscoveryTriggerPayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    tracker: RequestTracker = Depends(get_request_tracker),
    request_id: str = None,
):
    """
    Trigger resource discovery for a cloud account.
    Discovers all resources and their costs.
    """
    try:
        # Check if discovery is configured
        selected_types = await discovery_manager.get_selected_resource_types(
            project_name,
            cloud_platform,
            account_id
        )

        if not selected_types:
            error_msg = (
                "Discovery is not configured for this cloud account. "
                "Please configure resource types before running discovery."
            )
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=error_msg)

        # Get version defaults from config
        query_engine_version = ConfigManager.get_config('query_engine_versions', 'query_engine_version')
        compliance_engine_version = ConfigManager.get_config('query_engine_versions', 'compliance_engine_version')
        plugin_version = ConfigManager.get_config('query_engine_versions', 'plugin_versions', cloud_platform)

        # Initialize discovery trigger (reuse existing!)
        discovery_trigger = DiscoveryJobTrigger(
            tracker,
            request_id,
            ConfigManager,
            log_persistence=log_persistence,
            pool_manager=discovery_pool_manager,
        )

        # Get authentication (reuse existing!)
        cloudauth = MultiCloudAuthentication(
            cloud_platform=cloud_platform,
            project_manager=project_manager,
            project_name=project_name,
            account_id=account_id,
        )
        await cloudauth.initialize()
        auth_env_vars = await cloudauth.get_auth_env_vars()

        # Get pre-built discovery queries (now uses selected resource types)
        try:
            discovery_query = await discovery_manager.build_discovery_query(
                cloud_platform,
                project_name,
                account_id
            )
            cost_query = discovery_manager.build_cost_query(cloud_platform)
        except ValueError as e:
            error_msg = str(e)
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=error_msg)

        # Store discovery config in database (avoids Fargate env var size limits)
        discovery_config = {
            "discovery_query": discovery_query,
            "cost_query": cost_query
        }

        success, message = await tracker.update_discovery_config(request_id, discovery_config)
        if not success:
            error_msg = f"Failed to store discovery config: {message}"
            await tracker.update_error_details(request_id, error_msg)
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=500, detail=error_msg)

        # Trigger discovery (queries will be fetched via HTTP by runner)
        result = await discovery_trigger.trigger_discovery_command(
            project_name=project_name,
            run_details={"auth_env_vars": auth_env_vars},
            run_type="discovery",
            request_id=request_id,
            cloud_platform=cloud_platform,
            query_engine_version=query_engine_version,
            compliance_engine_version=compliance_engine_version,
            plugin_version=plugin_version,
            timeout_hours=payload.task_timeout_hours
        )

        if result["status"] == "error":
            await tracker.update_error_details(request_id, result["error"])
            await tracker.update_request_state(request_id, "failed")
            raise HTTPException(status_code=400, detail=result["error"])

        await tracker.update_request_state(request_id, "in progress")
        return {
            "status": "success",
            "message": "Discovery triggered successfully",
            "request_id": request_id,
            "task_arn": result["task_arn"]
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to trigger discovery: {str(e)}"
        await tracker.update_error_details(request_id, error_msg)
        await tracker.update_request_state(request_id, "failed")
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


# ---- Scheduled runs ----

@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/list"
)
@permissions(["project_cloud_account_get"])
async def list_scheduled_runs(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    scheduler: Scheduler = Depends(get_scheduler),
    user_permissions: List[str] = Depends(lambda: []),
):
    """List all schedules for a specific cloud account."""
    try:
        # Create filters with explicit paths
        filters = {
            "payload.cloud_platform": cloud_platform,
            "payload.cloud_account": account_id,
        }

        schedules = await scheduler.list_schedules(project_name, filters)
        logger.debug(f"Returned {len(schedules)} schedules for cloud_platform={cloud_platform}, account_id={account_id}")
        return {"schedules": schedules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/{schedule_id}"
)
@permissions(["project_cloud_account_get"])
async def get_scheduled_run(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    schedule_id: str,
    user: dict = Depends(authenticate_http_user),
    scheduler: Scheduler = Depends(get_scheduler),
    user_permissions: List[str] = Depends(lambda: []),  # Add this parameter
):
    """Get details of a specific schedule."""
    try:
        schedule = await scheduler.get_schedule(schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        if schedule["project_name"] != project_name:
            raise HTTPException(status_code=404, detail="Schedule not found")

        return schedule
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/{schedule_id}"
)
@permissions(["project_cloud_account_edit"])
async def delete_scheduled_run(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    schedule_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    scheduler: Scheduler = Depends(get_scheduler),
):
    """Delete a specific schedule."""
    try:
        await scheduler.delete_schedule(schedule_id, project_name)
        return {"message": "Schedule deleted successfully", "schedule_id": schedule_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/{schedule_id}/requests"
)
@permissions(["project_cloud_account_get"])
async def list_schedule_requests(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    schedule_id: str,
    user: dict = Depends(authenticate_http_user),
    tracker: RequestTracker = Depends(get_request_tracker),
    user_permissions: List[str] = Depends(lambda: []),
):
    """List all requests triggered by a specific schedule."""
    try:
        custom_filter = {"schedule_id": schedule_id}
        success, result = await tracker.list_requests(
            project_name=project_name,
            request_type="query_run",
            custom_filter=custom_filter,
        )

        if not success:
            raise HTTPException(status_code=500, detail=result)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/{schedule_id}/state"
)
@permissions(["project_schedule_create"])
async def update_schedule_state(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    schedule_id: str,
    state: Models.ScheduleStateUpdate,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    scheduler: Scheduler = Depends(get_scheduler),
):
    """Update the state of a schedule (enable/disable)."""
    try:
        result = await scheduler.update_schedule_status(
            schedule_id=schedule_id, project_name=project_name, new_status=state.state
        )
        return result
    except Exception as e:
        logger.debug(e)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Discovery dashboard ----

@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{cloud_account_id}/dashboard",
    response_model=Models.DashboardResponse,
    tags=["Discovery Dashboard"]
)
@permissions(["project_cloud_account_get"])
async def get_cloud_account_dashboard(
    project_name: str,
    cloud_platform: str,
    cloud_account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    history_limit: int = 10
):
    """
    Get comprehensive dashboard for a single cloud account.

    Includes:
    - Latest discovery summary
    - Statistical insights and anomalies
    - Chart-ready data
    - Discovery history with trends
    """
    try:
        # 1. Get latest discovery data
        success, status_code, latest_data = await discovery_dashboard.get_latest_discovery_data(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=cloud_account_id,
            request_tracker=request_tracker
        )

        if not success:
            raise HTTPException(status_code=status_code, detail=latest_data)

        # 2. Get discovery history
        history = await discovery_dashboard.get_discovery_history(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=cloud_account_id,
            request_tracker=request_tracker,
            limit=history_limit
        )

        # 3. Run statistical analysis (if enough history)
        insights = {}
        if len(history) >= 2:
            analyzer = DiscoveryAnalyzer(history)
            insights = analyzer.get_insights()
        else:
            insights = {
                "message": "Run more discoveries to unlock insights",
                "anomalies": {"cost_anomalies": [], "resource_anomalies": []},
                "trends": {"cost": None, "resources": None},
                "recommendations": ["Run at least 2 discoveries to enable analysis"]
            }

        # 4. Build chart data
        chart_builder = ChartDataBuilder(latest_data)
        chart_data = chart_builder.build_all_charts()

        # Add trend charts if we have history
        if len(history) >= 2:
            chart_data["cost_trend_line"] = chart_builder.build_cost_trend_line_chart(history)
            chart_data["resource_trend_line"] = chart_builder.build_resource_trend_line_chart(history)
            chart_data["combined_trend"] = chart_builder.build_combined_trend_chart(history)
            chart_data["tagging_compliance"] = chart_builder.build_tagging_compliance_chart()

        # 5. Combine everything
        response = {
            "cloud_account_id": cloud_account_id,
            "provider": cloud_platform,
            "request_id": latest_data["request_id"],
            "discovered_at": latest_data["discovered_at"],
            "summary": latest_data["summary"],
            "insights": insights,
            "chart_data": chart_data,
            "resources": latest_data.get("resources", []),
            "discovery_history": history
        }

        logger.info(f"Dashboard generated for {project_name}/{cloud_account_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Dashboard generation failed: {str(e)}")


@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_account_id}/history",
    tags=["Discovery Dashboard"]
)
async def get_discovery_history_endpoint(
    project_name: str,
    cloud_account_id: str,
    request: Request,
    limit: int = 20
):
    """
    Get discovery history for a cloud account.
    """
    try:
        session_user = request.cookies.get("username")
        if not session_user:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Validate limit
        if limit > 50:
            limit = 50

        # Get project to determine cloud platform
        success, project = await project_manager.get_project(project_name)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")

        cloud_platform = None
        for account in project.get('cloud_accounts', []):
            if account.get('account_id') == cloud_account_id:
                cloud_platform = account.get('cloud_platform')
                break

        if not cloud_platform:
            raise HTTPException(status_code=404, detail="Cloud account not found")

        history = await discovery_dashboard.get_discovery_history(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=cloud_account_id,
            request_tracker=request_tracker,
            limit=limit
        )

        return {
            "success": True,
            "count": len(history),
            "history": history
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_account_id}/resources",
    tags=["Discovery Dashboard"]
)
async def get_resources_with_filters(
    project_name: str,
    cloud_account_id: str,
    request: Request,
    resource_type: Optional[str] = None,
    region: Optional[str] = None,
    tagged_only: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50
):
    """
    Get resources with filtering and pagination.
    """
    try:
        session_user = request.cookies.get("username")
        if not session_user:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Validate pagination
        if page_size > 200:
            page_size = 200
        if page < 1:
            page = 1

        # Get project
        success, project = await project_manager.get_project(project_name)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")

        cloud_platform = None
        for account in project.get('cloud_accounts', []):
            if account.get('account_id') == cloud_account_id:
                cloud_platform = account.get('cloud_platform')
                break

        if not cloud_platform:
            raise HTTPException(status_code=404, detail="Cloud account not found")

        # Get latest discovery
        success, status_code, latest_data = await discovery_dashboard.get_latest_discovery_data(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=cloud_account_id,
            request_tracker=request_tracker
        )

        if not success:
            raise HTTPException(status_code=status_code, detail=latest_data)

        resources = latest_data.get("resources", [])

        # Apply filters
        filtered = resources

        if resource_type:
            filtered = [r for r in filtered if r['resource_type'] == resource_type]

        if region:
            filtered = [r for r in filtered if r['region'] == region]

        if tagged_only:
            filtered = [r for r in filtered if r.get('tags') and len(r['tags']) > 0]

        if search:
            search_lower = search.lower()
            filtered = [
                r for r in filtered
                if search_lower in r['resource_name'].lower() or search_lower in r['resource_id'].lower()
            ]

        # Paginate
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = filtered[start:end]

        return {
            "success": True,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "resources": paginated
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resource filtering failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_account_id}/insights",
    tags=["Discovery Dashboard"]
)
async def get_insights_only(
    project_name: str,
    cloud_account_id: str,
    request: Request,
    history_limit: int = 10
):
    """
    Get only insights and anomalies (lighter weight than full dashboard).
    """
    try:
        session_user = request.cookies.get("username")
        if not session_user:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get project
        success, project = await project_manager.get_project(project_name)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")

        cloud_platform = None
        for account in project.get('cloud_accounts', []):
            if account.get('account_id') == cloud_account_id:
                cloud_platform = account.get('cloud_platform')
                break

        if not cloud_platform:
            raise HTTPException(status_code=404, detail="Cloud account not found")

        # Get history
        history = await discovery_dashboard.get_discovery_history(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=cloud_account_id,
            request_tracker=request_tracker,
            limit=history_limit
        )

        if len(history) < 2:
            return {
                "success": True,
                "message": "Not enough data for insights",
                "insights": None
            }

        # Analyze
        analyzer = DiscoveryAnalyzer(history)
        insights = analyzer.get_insights()

        return {
            "success": True,
            "insights": insights,
            "discoveries_analyzed": len(history)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Insights generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_account_id}/compare",
    tags=["Discovery Dashboard"]
)
async def compare_discoveries_endpoint(
    project_name: str,
    cloud_account_id: str,
    request: Request,
    request_id_1: str = Body(...),
    request_id_2: str = Body(...)
):
    """
    Compare two discoveries to see what changed.
    """
    try:
        session_user = request.cookies.get("username")
        if not session_user:
            raise HTTPException(status_code=401, detail="Authentication required")

        success, status_code, comparison = await discovery_dashboard.compare_discoveries(
            request_id_1=request_id_1,
            request_id_2=request_id_2
        )

        if not success:
            raise HTTPException(status_code=status_code, detail=comparison)

        return {
            "success": True,
            "comparison": comparison
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Comparison failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/benchmark_results/{request_id}")
@permissions([])
@validate_resource()
async def get_benchmark_results(
    request: Request,
    project_name: str,
    cloud_platform: str,
    account_id: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    """
    Fetch and parse benchmark results from local filesystem for a given request.
    Returns aggregated data optimized for compliance remediation display.
    """
    try:
        artifacts_base = os.environ.get('ARTIFACTS_STORAGE_PATH', '/app/data/artifacts')
        artifacts_prefix = os.environ.get('ARTIFACTS_PREFIX', 'query-results')

        # Construct filesystem path for benchmark results
        base_path = os.path.join(artifacts_base, artifacts_prefix, request_id)

        if not os.path.isdir(base_path):
            return JSONResponse(
                status_code=404,
                content={"error": "No results found for this benchmark run"}
            )

        # Find the benchmark JSON file
        benchmark_file = None
        for filename in os.listdir(base_path):
            if 'benchmark_' in filename and filename.endswith('.json'):
                benchmark_file = os.path.join(base_path, filename)
                break

        if not benchmark_file:
            return JSONResponse(
                status_code=404,
                content={"error": "Benchmark results file not found"}
            )

        # Read and parse the JSON file
        with open(benchmark_file, 'r') as f:
            benchmark_data = json.load(f)

        # Parse and aggregate the results for remediation focus
        aggregated_data = aggregate_benchmark_results(benchmark_data)

        if aggregated_data.get('credential_error'):
            return JSONResponse(
                status_code=422,
                content={
                    "error": "All benchmark controls failed with execution errors. "
                             "This typically indicates invalid or missing cloud credentials.",
                    "credential_error": True
                }
            )

        return JSONResponse(content=aggregated_data)

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Invalid JSON in benchmark results file"}
        )
    except Exception as e:
        logger.error(f"Error processing benchmark results: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process benchmark results: {str(e)}"}
        )


def aggregate_benchmark_results(benchmark_data):
    """
    Parse benchmark JSON and extract actionable failed controls for remediation.
    Returns only ALARM and ERROR status controls with resource details.
    """
    # Validate input
    if not benchmark_data or not isinstance(benchmark_data, dict):
        raise ValueError("Invalid benchmark data: expected a dictionary")

    failed_controls = []
    summary_stats = {
        "alarm": 0,
        "ok": 0,
        "skip": 0,
        "error": 0,
        "info": 0
    }

    # Extract summary from root
    if 'summary' in benchmark_data and 'status' in benchmark_data['summary']:
        summary_stats = benchmark_data['summary']['status']

    # Detect credential/connectivity failure: nothing ran, every control errored
    total_ran = (summary_stats.get('alarm', 0) + summary_stats.get('ok', 0) +
                 summary_stats.get('skip', 0) + summary_stats.get('info', 0))
    if total_ran == 0 and summary_stats.get('error', 0) > 0:
        return {
            'credential_error': True,
            'summary': {
                'alarm': 0, 'ok': 0, 'skip': 0,
                'error': summary_stats.get('error', 0),
                'info': 0, 'total_applicable': 0, 'compliance_score': 0
            },
            'benchmark_title': benchmark_data.get('title', 'Compliance Benchmark'),
            'failed_controls': [],
            'total_failed_controls': 0
        }

    # Recursively extract controls from groups
    def extract_controls(node, article_path=""):
        if 'groups' in node and node['groups']:
            for group in node.get('groups', []):
                # Build article/section path
                group_title = group.get('title', '')
                new_path = f"{article_path} > {group_title}" if article_path else group_title
                extract_controls(group, new_path)

        if 'controls' in node and node['controls']:
            for control in node.get('controls', []):
                control_summary = control.get('summary', {})
                alarm_count = control_summary.get('alarm', 0)
                error_count = control_summary.get('error', 0)
                ok_count = control_summary.get('ok', 0)
                skip_count = control_summary.get('skip', 0)

                # Extract service from tags
                service = control.get('tags', {}).get('service', 'Unknown')

                # Get affected resources (both failed and passed)
                affected_resources = []
                if control.get('results'):
                    for result in control.get('results', []):
                        if result.get('status') in ['alarm', 'error']:
                            affected_resources.append({
                                'resource': result.get('resource', 'N/A'),
                                'reason': result.get('reason', 'No reason provided'),
                                'status': result.get('status', 'unknown')
                            })

                # Determine overall status
                if alarm_count > 0 or error_count > 0:
                    status = 'alarm'
                elif ok_count > 0:
                    status = 'ok'
                elif skip_count > 0:
                    status = 'skip'
                else:
                    status = 'info'

                failed_controls.append({
                    'control_id': control.get('control_id', 'N/A'),
                    'title': control.get('title', 'No title'),
                    'description': control.get('description', ''),
                    'service': service,
                    'article': article_path if article_path else 'N/A',
                    'severity': control.get('severity', ''),
                    'alarm_count': alarm_count,
                    'error_count': error_count,
                    'ok_count': ok_count,
                    'skip_count': skip_count,
                    'total_failed': alarm_count + error_count,
                    'status': status,
                    'affected_resources': affected_resources
                })

    # Start extraction from root
    extract_controls(benchmark_data)

    # Calculate compliance score
    total_applicable = summary_stats['alarm'] + summary_stats['ok'] + summary_stats['error']
    compliance_score = round((summary_stats['ok'] / total_applicable * 100), 1) if total_applicable > 0 else 0

    return {
        'summary': {
            'alarm': summary_stats['alarm'],
            'ok': summary_stats['ok'],
            'skip': summary_stats['skip'],
            'error': summary_stats['error'],
            'info': summary_stats.get('info', 0),
            'total_applicable': total_applicable,
            'compliance_score': compliance_score
        },
        'benchmark_title': benchmark_data.get('title', 'Compliance Benchmark'),
        'failed_controls': failed_controls,
        'total_failed_controls': len(failed_controls)
    }
