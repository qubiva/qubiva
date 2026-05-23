"""
Dashboard template page routes for Qubiva.

ALL /dashboard/* HTML page routes that render Jinja2 templates.
Also includes the Cloud Analyst dashboard page.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, Request

from app.deps import (
    ConfigManager,
    project_manager,
    templates,
)
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions, validate_resource

_ENGINE_LABELS = {"tofu": "OpenTofu", "terraform": "Terraform"}


def _iac_engine_context() -> dict:
    """Return IaC engine name and human-readable label for templates."""
    engine = ConfigManager.get_config("terraform", "engine") or "tofu"
    return {
        "iac_engine": engine,
        "iac_engine_label": _ENGINE_LABELS.get(engine, engine.title()),
    }


logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/dashboard")
@permissions([])
async def dashboard_home(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user["username"], "permissions": user_permissions},
    )


@router.get("/dashboard/ai-governance")
@permissions(["org_admin"])
async def dashboard_ai_governance(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_ai_governance.html",
        {"request": request, "user": user["username"], "permissions": user_permissions},
    )


@router.get("/dashboard/api-tokens")
@permissions([])
async def dashboard_api_tokens(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_api_token_manager.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects")
@permissions([])
async def dashboard_projects(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_projects.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/create")
@permissions(["org_project_create"])
async def dashboard_create_project(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_create_project.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/add-users")
@permissions(["org_user_add"])
async def dashboard_create_users(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_add_users.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/manage-org-policy")
@permissions([])
async def dashboard_manage_org_policy(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_manage_org_policy.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/manage-github-app")
@permissions(["org_admin"])
async def dashboard_manage_github_app(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_github_app_config.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/manage-users")
@permissions(["org_user_roles_edit"])
async def dashboard_manage_users(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_manage_users.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/manage-sso")
@permissions(["org_admin"])
async def dashboard_manage_sso(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_manage_sso.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/edit")
@validate_resource()
@permissions(["project_edit"])
async def dashboard_edit_project(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_edit_project.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}")
@validate_resource()
@permissions(["project_get"])
async def dashboard_project_details(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_project_details.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/cloud_accounts")
@validate_resource()
@permissions(["project_get"])
async def dashboard_project_cloud_accounts(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_project_cloud_accounts.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/git_repos")
@validate_resource()
@permissions(["project_get"])
async def dashboard_project_git_repos(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_project_github_repos.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/cloud_accounts/create")
@validate_resource()
@permissions(["project_cloud_account_create"])
async def dashboard_create_cloud_account(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_create_cloud_account.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/cloud_accounts/{provider_name}/{account_id}/edit"
)
@validate_resource()
@permissions(["project_cloud_account_edit"])
async def dashboard_edit_cloud_account(
    request: Request,
    project_name: str,
    provider_name: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_edit_cloud_account.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}"
)
@validate_resource()
@permissions(["project_cloud_account_get"])
async def dashboard_cloud_account_details(
    request: Request,
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_cloud_account.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/logs/{request_id}"
)
@permissions([])
@validate_resource()
async def dashboard_cloud_account_logs(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_logs_viewer.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/{schedule_id}"
)
@permissions([])
@validate_resource()
async def schedule_run_details(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_project_cloud_account_scheduled_run_details.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs"
)
@validate_resource()
@permissions([])
async def list_cloud_account_scheduled_runs(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_project_cloud_account_scheduled_runs.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/scheduled_runs/{schedule_id}/logs/{request_id}"
)
@validate_resource()
@permissions([])
async def scheduled_query_execution_logs(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_logs_viewer.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/git_repos/add")
@validate_resource(check_only_project=True)
@permissions(["project_git_repo_add"])
async def dashboard_add_github_repo(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_add_github_repo.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/git_repos/{repo_name}/edit")
@validate_resource()
@permissions(["project_git_repo_edit"])
async def dashboard_view_github_repo(
    request: Request,
    project_name: str,
    repo_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_edit_github_account.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/workspaces")
@validate_resource()
@permissions(["project_get"])
async def dashboard_workspaces(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_project_workspaces.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/workspaces/create")
@validate_resource(check_only_project=True)
@permissions(["project_workspace_create"])
async def dashboard_create_workspace(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    roles = await project_manager.get_user_roles_by_project(
        user["username"], project_name
    )
    "admin" in roles[1] if roles[0] else False
    return templates.TemplateResponse(
        "dashboard_create_workspace.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
            **_iac_engine_context(),
        },
    )


@router.get("/dashboard/projects/{project_name}/workspaces/{workspace_name}/edit")
@permissions(["project_workspace_edit"])
@validate_resource()
async def dashboard_edit_workspace(
    request: Request,
    project_name: str,
    workspace_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_edit_workspace.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
            **_iac_engine_context(),
        },
    )


@router.get("/dashboard/projects/{project_name}/workspaces/{workspace_name}")
@permissions([])
@validate_resource()
async def dashboard_terraform_executor(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_terraform_executor.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
            **_iac_engine_context(),
        },
    )


@router.get(
    "/dashboard/projects/{project_name}/workspaces/{workspace_name}/logs/{request_id}"
)
@permissions([])
@validate_resource()
async def terraform_execution_logs(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_logs_viewer.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/tasks")
@permissions([])
@validate_resource()
async def view_tasks(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_task_manager.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/tasks/{task_id}")
@permissions([])
@validate_resource()
async def view_task(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_task_manager.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/cloud_accounts/{provider_name}/{account_id}/alerts")
@permissions([])
@validate_resource()
async def dashboard_alerts(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_alerts.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/cloud_accounts/{provider_name}/{account_id}/alerts/{alert_id}")
@permissions([])
@validate_resource()
async def dashboard_alert_detail(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
    resource_details: dict = Depends(lambda: {}),
):
    return templates.TemplateResponse(
        "dashboard_alerts.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/credentials")
@validate_resource()
@permissions(["project_credential_get"])
async def dashboard_project_credentials(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_project_credentials.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/tokens")
@validate_resource(check_only_project=True)
@permissions(["project_token_list"])
async def dashboard_project_tokens(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_project_tokens.html",
        {
            "request": request,
            "project_name": project_name,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/credentials/create")
@validate_resource(check_only_project=True)
@permissions(["project_credential_create"])
async def dashboard_create_credential(
    request: Request,
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_create_credential.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/projects/{project_name}/credentials/{credential_name}/edit")
@validate_resource()
@permissions(["project_credential_edit"])
async def dashboard_edit_credential(
    request: Request,
    project_name: str,
    credential_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return templates.TemplateResponse(
        "dashboard_edit_credential.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
        },
    )


@router.get("/dashboard/analyst")
@permissions(["org_analyst_use"])
async def dashboard_analyst(
    request: Request,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Top-level Cloud Analyst page -- user picks project/scope in the UI."""
    # Check if LLM is properly configured (provider + model + API key)
    import os
    from app.deps import is_analyst_ready
    analyst_ready = is_analyst_ready()
    is_demo = bool(os.getenv("APP_BANNER_MESSAGE"))
    return templates.TemplateResponse(
        "dashboard_analyst.html",
        {
            "request": request,
            "user": user["username"],
            "permissions": user_permissions,
            "analyst_ready": analyst_ready,
            "is_demo": is_demo,
        },
    )
