"""
Route decorators for Qubiva.

Provides reusable decorators for permission checks, resource validation,
request tracking, and scheduling.
"""

import logging
from typing import Dict, Any, List, Callable

from functools import wraps
from fastapi import BackgroundTasks, HTTPException, Request, status

from app.deps import (
    project_manager,
    project_resource_locator,
    rbac,
    templates,
    get_scheduler,
)
from app.request_manager import RequestTracker

logger = logging.getLogger("uvicorn.error")


def track_request(
    request_type: str,
    additional_details_func: Callable[[Dict[str, Any]], Dict[str, Any]] = None,
):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            user = kwargs.get("user")
            tracker: RequestTracker = kwargs.get("tracker")
            background_tasks: BackgroundTasks = kwargs.get("background_tasks")

            if not all([request, user, tracker]):
                raise ValueError(
                    "Missing required dependencies: request, user, or tracker"
                )

            additional_details = {}
            if additional_details_func:
                all_inputs = {**kwargs, **await request.json()}
                additional_details = additional_details_func(all_inputs)

            schedule_id = request.headers.get("X-Schedule-ID")
            if schedule_id:
                additional_details["schedule_id"] = schedule_id
                additional_details["is_scheduled_run"] = True

            # Create the request and get the request_id
            success, result = await tracker.create_request(
                requested_by=user["username"],
                request_type=request_type,
                additional_details=additional_details,
            )

            if not success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create request: {result}",
                )

            request_id = result
            kwargs["request_id"] = request_id

            # Return the request_id immediately
            response = {"status": "in progress", "request_id": request_id}

            # Trigger Terraform command in background
            background_tasks.add_task(func, *args, **kwargs)

            return response

        return wrapper

    return decorator


def schedulable_endpoint():
    """
    A decorator to enable scheduling for specific API endpoints.
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract necessary components
            request: Request = kwargs.get("request")
            payload = kwargs.get("payload")
            project_name = kwargs.get("project_name")
            user = kwargs.get("user")

            if not request or not payload or not project_name:
                raise HTTPException(
                    status_code=400,
                    detail="Missing required request, payload, or project_name.",
                )

            # Check if the request is for scheduling
            schedule_info = getattr(payload, "schedule", None)
            if schedule_info:
                frequency = schedule_info.get("frequency")
                if not frequency:
                    raise HTTPException(
                        status_code=400, detail="Schedule frequency is required."
                    )

                # Get username from user dict
                username = user.get("username") if user else None
                if not username:
                    raise HTTPException(
                        status_code=500,
                        detail="Unable to determine username to perform create_schedule operation.",
                    )

                # Prepare scheduling payload
                path = request.url.path
                payload_dict = payload.dict()
                payload_dict.pop("schedule", None)

                # Add cloud_platform and account_id from path parameters if they exist
                if "cloud_platform" in kwargs:
                    payload_dict["cloud_platform"] = kwargs["cloud_platform"]
                if "account_id" in kwargs:
                    payload_dict["cloud_account"] = kwargs["account_id"]

                # Add run_type for discovery endpoints
                if "/run_discovery" in path:
                    payload_dict["run_type"] = "discovery"

                try:
                    # Use the Scheduler instance to create the schedule
                    scheduler_instance = await get_scheduler()
                    result = await scheduler_instance.create_schedule(
                        endpoint=path,
                        payload=payload_dict,
                        frequency=frequency,
                        project_name=project_name,
                        username=username,
                    )
                    return {
                        "status": "success",
                        "message": "Schedule created successfully.",
                        "data": result,
                    }
                except ValueError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid schedule expression: {str(e)}",
                    )
                except Exception as e:
                    logger.error(f"Failed to create schedule: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create schedule: {str(e)}",
                    )

            # Proceed to the actual endpoint logic if not scheduling
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def permissions(required_permissions: List[str]):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("user")
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not authenticated",
                )

            # Allow internal service to bypass permission checks
            if user["username"] in ["scheduler", "internal_service"]:
                logger.debug("Internal service detected")
                kwargs["user_permissions"] = [
                    "*"
                ]  # Mock all permissions for internal calls
                return await func(*args, **kwargs)

            project_name = kwargs.get("project_name")
            project_roles = []
            org_roles = user.get("org_roles", []) or []

            if project_name:
                success, project = await project_manager.get_project_details(
                    project_name
                )
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Failed to get project {project_name}. Error: {project}",
                    )
                (
                    success,
                    project_roles,
                ) = await project_manager.get_user_roles_by_project(
                    username=user.get("username"),
                    project_name=project_name,
                    is_org_user=bool(org_roles),
                ) or (
                    False,
                    [],
                )
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to check user permissions. Error: {project_roles}",
                    )
            # Auto-grant project_get to all project members
            has_permission, user_permissions = rbac.check_permissions(
                required_permissions, project_roles, org_roles
            )

            # Auto-grant project_get to all project members if they don't have it
            if (
                project_name
                and project_roles
                and "project_get" in required_permissions
                and not has_permission
            ):
                logger.debug(
                    f"Auto-granting project_get to project member: {user.get('username')}"
                )
                user_permissions = list(user_permissions) if user_permissions else []
                if "project_get" not in user_permissions:
                    user_permissions.append("project_get")
                kwargs["user_permissions"] = user_permissions
                return await func(*args, **kwargs)

            if not has_permission:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions",
                )

            # Update kwargs with user_permissions.
            kwargs["user_permissions"] = user_permissions

            # Call the wrapped function with updated kwargs
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def validate_resource(check_only_project: bool = False):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            project_name = kwargs.get("project_name")

            if not project_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Project name is missing in the request",
                )

            # Instantiate the ProjectResourceLocator

            locator = project_resource_locator

            # Step 1: Validate that the project exists
            project_exists, project_details = await locator.validate_project(
                project_name
            )
            if not project_exists:
                return templates.TemplateResponse(
                    "dashboard_404.html",
                    {
                        "request": request,
                        "message": project_details,
                    },
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # If only project validation is requested, skip further resource checks
            if check_only_project:
                return await func(*args, **kwargs)

            # Step 2: Determine the resource type and name based on the URL path
            url_path = str(request.url.path)
            (
                resource_type,
                resource_name,
                cloud_platform,
                _,
            ) = locator.extract_resource_from_url(url_path, project_name)

            # Step 3: If there is no nested resource to validate, continue to the endpoint
            if not resource_type or not resource_name:
                return await func(*args, **kwargs)

            # Step 4: Validate the nested resource existence
            resource_exists, resource_details = await locator.validate_resource_path(
                project_name, resource_type, resource_name, cloud_platform
            )

            if not resource_exists:
                return templates.TemplateResponse(
                    "dashboard_404.html",
                    {
                        "request": request,
                        "message": f"Resource '{resource_name}' of type '{resource_type}' not found in project '{project_name}'",
                    },
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # Add resource details to the request context (optional)
            kwargs["resource_details"] = resource_details

            return await func(*args, **kwargs)

        return wrapper

    return decorator
