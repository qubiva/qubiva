"""
Organization management routes for Qubiva.

User CRUD, org roles, policy repo, deactivation/reactivation.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.deps import (
    authenticator,
    audit_logger,
    project_manager,
    rbac,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/api/v1/org/list_org_roles")
async def list_org_roles(user: dict = Depends(authenticate_http_user)):
    return rbac.get_all_org_roles()


@router.post("/api/v1/org/users/add")
@permissions(["org_user_add"])
async def create_users(
    data: Models.CreateUsersRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    # Convert each UserCreateData instance to a dictionary
    users_data = [u.dict() for u in data.users]
    username = user.get("username", "")
    # Call the create_users method with the list of dictionaries
    success, message = await project_manager.create_users(users=users_data, acting_user=username)

    if success:
        for u in data.users:
            await audit_logger.log_event("create_user", username, "user", u.username)
        return {"message": message, "user_count": len(data.users)}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.post("/api/v1/org/users/modify-users-org-roles")
@permissions(["org_user_roles_edit"])
async def modify_users_org_roles(
    data: Models.ModifyOrgUsersRolesRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    # Convert Pydantic model to a list of dictionaries
    users_data = [
        user.dict() for user in data.users
    ]  # `user.dict()` converts each model instance to a dictionary

    # Call the modify_users_org_roles method with the list of users
    username = user.get("username", "")
    success, message = await project_manager.modify_users_org_roles(users=users_data, acting_user=username)

    if success:
        for u in users_data:
            await audit_logger.log_event("modify_org_roles", username, "user", u.get("username", ""), details={"new_roles": u.get("org_roles", [])})
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.post("/api/v1/org/users/delete")
@permissions(["org_user_delete"])
async def delete_users(
    data: Models.DeleteUsersRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    # Extract the list of usernames from the request data
    usernames = data.usernames

    # Call the delete_users method with the list of usernames
    acting_username = user.get("username", "")
    success, message = await project_manager.delete_users(usernames=usernames, acting_user=acting_username)

    if success:
        for uname in usernames:
            await audit_logger.log_event("delete_user", acting_username, "user", uname)
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.get("/api/v1/users/search/")
async def search_users(query: str, user: dict = Depends(authenticate_http_user)):
    return await authenticator.search_users(query)


@router.get("/api/v1/users/get_all_users/")
async def get_all_users(user: dict = Depends(authenticate_http_user)):
    return await authenticator.get_all_users()


@router.post("/api/v1/org/users/deactivate")
@permissions(["org_admin"])
async def deactivate_user(
    deactivate_request: Models.DeactivateUserRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Deactivate a user (soft delete)."""
    acting_username = user.get("username", "")
    success, message = await project_manager.deactivate_user(
        username=deactivate_request.username,
        reason=deactivate_request.reason,
        acting_user=acting_username,
    )

    if success:
        await audit_logger.log_event("deactivate_user", acting_username, "user", deactivate_request.username, details={"reason": deactivate_request.reason})
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.post("/api/v1/org/users/reactivate")
@permissions(["org_admin"])
async def reactivate_user(
    reactivate_request: Models.ReactivateUserRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Reactivate a previously deactivated user."""
    acting_username = user.get("username", "")
    success, message = await project_manager.reactivate_user(
        username=reactivate_request.username,
        acting_user=acting_username,
    )

    if success:
        await audit_logger.log_event("reactivate_user", acting_username, "user", reactivate_request.username)
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.get("/api/v1/org/policy-repo")
@permissions(["org_admin"])
async def get_org_policy_repo(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, repo_data = await project_manager.get_org_policy_repo()
    if not success:
        raise HTTPException(status_code=500, detail=repo_data)

    if repo_data is None:
        return {"message": "No organization policy repository configured", "repo": None}

    return {"repo": repo_data}


@router.put("/api/v1/org/policy-repo")
@permissions(["org_admin"])
async def update_org_policy_repo(
    repo_data: Models.OrgPolicyRepoUpdate,  # You'll need to create this model
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, message = await project_manager.update_org_policy_repo(
        repo_url=repo_data.repo_url,
        branch=repo_data.branch,
        token=repo_data.token,
        policy_path=repo_data.policy_path,
        conftest_version=repo_data.conftest_version
    )

    if success:
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)
