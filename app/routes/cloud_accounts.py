"""
Cloud account and credential management routes for Qubiva.

Also includes git repo CRUD and cloud account search.
"""

import logging
import traceback
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import (
    audit_logger,
    project_manager,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# ---- Credentials ----

@router.get("/api/v1/projects/{project_name}/credentials")
@permissions(["project_credential_get"])
async def get_project_credentials(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, credentials = await project_manager.get_credentials_by_project(project_name)
    if success:
        return {"credentials": credentials}
    else:
        raise HTTPException(status_code=404, detail=credentials)


@router.post("/api/v1/projects/{project_name}/credentials")
@permissions(["project_credential_create"])
async def create_project_credential(
    project_name: str,
    credential_data: Models.CredentialData,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, message = await project_manager.create_credential(project_name, credential_data.dict(), acting_user=username)
    if success:
        await audit_logger.log_event("create_credential", username, "credential", credential_data.credential_name, project_name)
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.get("/api/v1/projects/{project_name}/credentials/search")
@permissions(["project_credential_get"])
async def search_credentials(
    project_name: str,
    query: str = Query("", description="Search term for filtering credentials"),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    try:
        logger.debug("JSR")
        logger.debug(f"Searching credentials in project {project_name} with query: '{query}'")

        # Use the existing ProjectManager method
        success, credentials = await project_manager.get_credentials_by_project(project_name)
        if not success:
            logger.error(f"Failed to get credentials: {credentials}")
            return {"results": []}

        logger.debug(f"Found {len(credentials)} total credentials for project {project_name}")

        # Filter credentials based on query (case-insensitive)
        if query.strip():
            query_lower = query.lower()
            filtered_credentials = [
                cred for cred in credentials
                if query_lower in cred.get("credential_name", "").lower() or
                   query_lower in cred.get("credential_type", "").lower()
            ]
        else:
            filtered_credentials = credentials

        # Format for select2 - EXACTLY matching your existing JS expectations
        results = [
            {
                "id": cred["credential_name"],
                "credential_name": cred["credential_name"],
                "credential_type": cred["credential_type"],
                "text": f"{cred['credential_name']} ({cred['credential_type']})"
            }
            for cred in filtered_credentials
        ]

        logger.debug(f"Returning {len(results)} filtered credentials")
        return {"results": results}

    except Exception as e:
        logger.error(f"Failed to search credentials: {str(e)}")
        logger.error(traceback.format_exc())
        return {"results": []}


@router.get("/api/v1/projects/{project_name}/credentials/{credential_name}")
@permissions(["project_credential_get"])
async def get_credential_details(
    project_name: str,
    credential_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, credential = await project_manager.get_credential_details(project_name, credential_name)
    if success:
        return credential
    else:
        raise HTTPException(status_code=404, detail=credential)


@router.put("/api/v1/projects/{project_name}/credentials/{credential_name}")
@permissions(["project_credential_edit"])
async def update_credential(
    project_name: str,
    credential_name: str,
    credential_update: Models.CredentialUpdate,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, message = await project_manager.update_credential(
        project_name, credential_name, credential_update.dict(), acting_user=username
    )
    if success:
        await audit_logger.log_event("update_credential", username, "credential", credential_name, project_name)
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.delete("/api/v1/projects/{project_name}/credentials/{credential_name}")
@permissions(["project_credential_delete"])
async def delete_credential(
    project_name: str,
    credential_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, message = await project_manager.delete_credential(project_name, credential_name, acting_user=username)
    if success:
        await audit_logger.log_event("delete_credential", username, "credential", credential_name, project_name)
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


# ---- Cloud account search ----

@router.get("/api/v1/projects/{project_name}/cloud_accounts/search")
@permissions(["project_cloud_account_get"])
async def search_cloud_accounts(
    project_name: str,
    query: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),  # Add this line
):
    success, results = await project_manager.search_cloud_accounts(project_name, query)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to search cloud accounts")

    return {"results": results}


# ---- Cloud accounts list ----

@router.get("/api/v1/projects/{project_name}/cloud_accounts")
@permissions(["project_get"])
async def get_cloud_accounts(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, cloud_accounts = await project_manager.get_cloud_accounts_by_project_name(
        project_name
    )
    if not success:
        raise HTTPException(status_code=404, detail=cloud_accounts)
    return cloud_accounts


# ---- Cloud account CRUD ----

@router.put("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/edit")
@permissions(["project_cloud_account_edit"])
async def edit_cloud_account(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    cloud_account_update: Models.CloudAccountUpdate,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    updated_account = {
        "cloud_platform": cloud_platform,
        "account_id": account_id,
        "variables": cloud_account_update.variables,
        "secrets": cloud_account_update.secrets,
    }

    # ONLY add the auth method that's actually provided
    if cloud_account_update.auth_secrets:
        updated_account["auth_secrets"] = cloud_account_update.auth_secrets

    if cloud_account_update.credential_reference:
        updated_account["credential_reference"] = cloud_account_update.credential_reference

    username = user.get("username", "")
    success, response = await project_manager.update_project_cloud_account(
        project_name, cloud_platform, account_id, updated_account, acting_user=username
    )
    if success:
        await audit_logger.log_event("update_cloud_account", username, "cloud_account", account_id, project_name, details={"cloud_platform": cloud_platform})
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.post("/api/v1/projects/{project_name}/add_cloud_account")
@permissions(["project_cloud_account_create"])
async def add_cloud_account_to_project(
    project_name: str,
    request: Models.CloudAccount,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.add_cloud_account_to_project(
        project_name, request.model_dump(), acting_user=username
    )
    if success:
        await audit_logger.log_event("add_cloud_account", username, "cloud_account", request.account_id, project_name, details={"cloud_platform": request.cloud_platform})
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.delete(
    "/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/delete"
)
@permissions(["project_cloud_account_delete"])
async def remove_cloud_account_from_project(
    project_name: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.delete_cloud_account_from_project(
        project_name, account_id, acting_user=username
    )
    if success:
        await audit_logger.log_event("delete_cloud_account", username, "cloud_account", account_id, project_name)
        return {"message": response}
    raise HTTPException(status_code=404, detail=response)


# ---- Git repos ----

@router.get("/api/v1/projects/{project_name}/git_repos/search")
@permissions(["project_git_repo_get"])
async def search_github_repos(
    project_name: str,
    query: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),  # Add this line
):
    success, results = await project_manager.search_github_repos(project_name, query)

    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to search GitHub repositories"
        )

    return {"results": results}


@router.post("/api/v1/projects/{project_name}/git_repos/add")
@permissions(["project_git_repo_add"])
async def add_github_repo_to_project(
    project_name: str,
    github_repo: Models.GitHubRepoDetails,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.add_github_repo_to_project(
        project_name, github_repo.dict(), acting_user=username
    )
    if success:
        await audit_logger.log_event("add_github_repo", username, "github_repo", github_repo.repo_name, project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.get("/api/v1/projects/{project_name}/git_repos")
@permissions(["project_get"])
async def get_all_github_repos_in_project(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, repos = await project_manager.get_github_repos_by_project(project_name)
    if not success:
        raise HTTPException(status_code=404, detail=repos)

    for repo in repos:
        repo.pop("token", None)
    return repos


@router.get("/api/v1/projects/{project_name}/git_repos/{repo_name}")
@permissions(["project_git_repo_get"])
async def get_github_repo_details(
    project_name: str,
    repo_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, repo_details = await project_manager.get_github_repo_details(
        project_name, repo_name
    )
    if success:
        return repo_details
    else:
        raise HTTPException(status_code=404, detail=repo_details)


@router.put("/api/v1/projects/{project_name}/git_repos/{repo_name}/edit")
@permissions(["project_git_repo_edit"])
async def edit_github_repo(
    project_name: str,
    repo_name: str,
    github_repo_update: Models.GitHubRepoUpdate,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.update_github_repo(
        project_name, repo_name, github_repo_update.dict(), acting_user=username
    )
    if success:
        await audit_logger.log_event("update_github_repo", username, "github_repo", repo_name, project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=400, detail=response)


@router.delete("/api/v1/projects/{project_name}/git_repos/{repo_name}/delete")
@permissions(["project_git_repo_delete"])
async def delete_github_repo_from_project(
    project_name: str,
    repo_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    username = user.get("username", "")
    success, response = await project_manager.delete_github_repo(
        project_name, repo_name, acting_user=username
    )
    if success:
        await audit_logger.log_event("delete_github_repo", username, "github_repo", repo_name, project_name)
        return {"message": response}
    else:
        raise HTTPException(status_code=404, detail=response)


# ---- Cloud account detail (catch-all, must be registered LAST) ----

@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}")
@permissions(["project_cloud_account_get"])
async def get_cloud_account_details(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, account_details = await project_manager.get_cloud_account_details(
        project_name, cloud_platform, account_id
    )
    if success:
        logger.debug("MIYAV BANGA")
        logger.debug(account_details)
        return account_details
    else:
        raise HTTPException(status_code=404, detail=account_details)
