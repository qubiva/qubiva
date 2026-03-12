"""
Project CRUD routes for Qubiva.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import (
    audit_logger,
    project_manager,
    rbac,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.post("/api/v1/org/projects/create")
@permissions(["org_project_create"])
async def create_project(
    project_data: Models.ProjectData,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):

    # Prepare the member_dicts if members are provided
    member_dicts = (
        [
            {"username": member.username, "roles": member.roles}
            for member in project_data.members
        ]
        if project_data.members
        else None
    )

    # Call the create_project method with all the new parameters
    username = user.get("username", "")
    success, response = await project_manager.create_project(
        project_name=project_data.project_name,
        description=project_data.description,
        members=member_dicts,
        variables=project_data.variables,
        secrets=project_data.secrets,
        acting_user=username,
    )

    if success:
        await audit_logger.log_event("create_project", username, "project", project_data.project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.delete("/api/v1/org/projects/{project_name}/delete")
@permissions(["org_project_delete"])
async def delete_project(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.delete_project(project_name, acting_user=username)
    if success:
        await audit_logger.log_event("delete_project", username, "project", project_name)
        return {"message": response}
    raise HTTPException(status_code=404, detail=response)


@router.get("/api/v1/projects/search")
async def search_projects(query: str, user: dict = Depends(authenticate_http_user)):
    success, results = await project_manager.search_projects(query)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to search projects")

    return {"results": results}


@router.get("/api/v1/projects/roles/list")
async def get_roles(user: dict = Depends(authenticate_http_user)):
    return rbac.get_all_project_roles()


# Project-related endpoints
@router.get("/api/v1/projects")
async def get_projects(user: dict = Depends(authenticate_http_user)):
    if user["org_roles"]:
        (
            success,
            projects_and_roles,
        ) = await project_manager.get_project_details_for_projects(
            username=user["username"], is_org_user=True
        )
        if success:
            return projects_and_roles
    if user["projects"]:
        (
            success,
            projects_and_roles,
        ) = await project_manager.get_project_details_for_projects(
            username=user["username"], project_names=user["projects"]
        )
        if success:
            return projects_and_roles
    return False


@router.get("/api/v1/projects/{project_name}")
@permissions(["project_get"])
async def get_project(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, project_details = await project_manager.get_project_details(project_name)
    if not success:
        raise HTTPException(status_code=404, detail=project_details)
    return project_details


@router.get("/api/v1/projects/{project_name}/members")
@permissions(["project_get"])
async def get_project_members(
    project_name: str,
    search: str = Query(
        "", description="Search term for filtering members by email"
    ),  # Added search query parameter
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    # Call the get_project_members method with the search query
    success, response = await project_manager.get_project_members(
        project_name=project_name,
        search_query=search,  # Pass search query to the backend method
    )

    if success:
        return response
    else:
        raise HTTPException(status_code=400, detail=response)


@router.put("/api/v1/projects/{project_name}/edit")
@permissions(["project_edit"])
async def edit_project(
    project_name: str,
    update_data: Models.ProjectUpdateRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.update_project(
        project_name,
        new_description=update_data.description,
        new_members=(
            [member.dict() for member in update_data.members]
            if update_data.members
            else None
        ),
        new_variables=update_data.variables,
        new_secrets=update_data.secrets,
        acting_user=username,
    )
    if success:
        await audit_logger.log_event("update_project", username, "project", project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)
