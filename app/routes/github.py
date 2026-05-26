"""
GitHub App configuration routes for Qubiva.
"""

import asyncio
import hashlib
import hmac
import logging
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse

from app.deps import project_manager
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.post("/api/v1/org/github-app/setup")
@permissions(["org_admin"])
async def setup_github_app(
    app_config: dict = Body(...),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    app_id = app_config.get('app_id')
    private_key = app_config.get('private_key')
    webhook_secret = app_config.get('webhook_secret')  # optional

    if not app_id or not private_key:
        raise HTTPException(status_code=400, detail="app_id and private_key are required")

    success, message = await project_manager.setup_github_app(app_id, private_key, webhook_secret=webhook_secret)
    if success:
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.post("/api/v1/org/github-app/installation")
@permissions(["org_admin"])
async def store_installation(
    installation_data: dict = Body(...),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    org_name = installation_data.get('org_name')
    installation_id = installation_data.get('installation_id')

    if not org_name or not installation_id:
        raise HTTPException(status_code=400, detail="org_name and installation_id are required")

    success, message = await project_manager.store_installation_mapping(org_name, installation_id)
    if success:
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.get("/api/v1/org/github-app/status")
@permissions(["org_admin"])
async def get_github_app_status(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, status = await project_manager.get_github_app_status()
    if success:
        return status
    else:
        raise HTTPException(status_code=500, detail=status)


@router.post("/api/v1/org/github-app/{org_name}/repos")
@permissions(["org_admin"])
async def list_github_repos_via_app(
    org_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, repos = await project_manager.github_app_api_call(org_name, operation="list_repos")
    if success:
        return {"repos": repos}
    else:
        raise HTTPException(status_code=400, detail=repos)


@router.get("/api/v1/org/github-app/{org_name}/repos/search")
@permissions(["org_admin"])
async def search_github_app_repos_for_picker(
    org_name: str,
    query: str = Query("", description="Search term for filtering repositories"),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Search GitHub App repositories for repository picker"""
    success, repos = await project_manager.search_github_app_repos_for_picker(org_name, query)
    if success:
        return {"results": repos}
    else:
        raise HTTPException(status_code=400, detail=repos)


@router.get("/api/v1/org/github-app/{org_name}/repos/{repo_name}")
@permissions(["org_admin"])
async def get_github_repo_via_app(
    org_name: str,
    repo_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, repo = await project_manager.github_app_api_call(org_name, repo_name, "get_repo")
    if success:
        return repo
    else:
        raise HTTPException(status_code=400, detail=repo)


@router.get("/github/install")
async def github_app_install_redirect(request: Request, slug: str = Query(..., description="GitHub App slug")):
    """
    Redirect users to GitHub for app installation.
    Accepts the GitHub App slug from query string and appends a proper redirect URI.
    """
    redirect_uri = str(request.url_for("github_app_callback"))  # absolute URL to /github/callback
    return RedirectResponse(f"https://github.com/apps/{slug}/installations/new?redirect_uri={redirect_uri}")


@router.get("/github/callback")
async def github_app_callback(
    request: Request,
    installation_id: int = Query(..., description="GitHub Installation ID"),
    setup_action: Optional[str] = Query(None),
):
    try:
        # 1) Resolve owner
        success, owner = await project_manager.get_org_name_from_installation(installation_id)
        if not success:
            return JSONResponse(status_code=400, content={"ok": False, "message": owner, "installation_id": installation_id})

        # 2) Validate installation belongs to saved App
        valid, error = await project_manager.validate_installation_belongs_to_app(installation_id)
        if not valid:
            return JSONResponse(status_code=400, content={"ok": False, "message": error, "installation_id": installation_id})

        # 3) Store mapping
        ok, msg = await project_manager.store_installation_mapping(org_name=owner, installation_id=installation_id)
        if not ok:
            return JSONResponse(status_code=400, content={"ok": False, "message": msg, "installation_id": installation_id, "owner": owner})

        return JSONResponse(status_code=200, content={"ok": True, "message": f"GitHub App installed for {owner}", "installation_id": installation_id, "owner": owner})

    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "message": f"Installation failed: {str(e)}", "installation_id": installation_id})


@router.delete("/api/v1/org/github-app/delete")
@permissions(["org_admin"])
async def delete_github_app_config(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Delete GitHub App configuration and all installation mappings"""
    success, message = await project_manager.delete_github_app_configuration()

    if success:
        return {"message": message}
    else:
        raise HTTPException(status_code=500, detail=message)


@router.get("/api/v1/org/github-app/{org_name}/test-auth")
@permissions(["org_admin"])
async def test_github_app_auth(
    org_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Lightweight test to verify GitHub App authentication works"""
    try:
        github_client = await project_manager.get_github_app_client(org_name)
        if not github_client:
            raise HTTPException(status_code=400, detail="Failed to authenticate with GitHub App")

        # Just check if we can access the authenticated user/org info
        try:
            # This is a lightweight call that just verifies authentication
            _ = github_client.get_user()  # Or get_organization(org_name)
            return {"message": "Authentication successful"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"GitHub API call failed: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication test failed: {str(e)}")


# ---------------------------------------------------------------------------
# GitHub Webhook endpoint
# ---------------------------------------------------------------------------

def _verify_signature(secret: str, payload: bytes, signature_header: str) -> bool:
    """Verify GitHub's HMAC-SHA256 webhook signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/github/webhook")
async def github_webhook(request: Request):
    """
    Receive and verify GitHub webhook events (push, pull_request).

    HMAC-SHA256 is verified using the stored webhook secret.  Events are
    dispatched asynchronously so GitHub receives 200 immediately.

    No authentication header required — GitHub signs every delivery.
    """
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "")

    # Retrieve webhook secret
    webhook_secret = await project_manager.get_webhook_secret()
    if webhook_secret is None:
        logger.warning("Webhook received but no webhook secret configured — rejecting")
        return Response(status_code=403, content="Webhook secret not configured")

    # HMAC verification
    if not _verify_signature(webhook_secret, payload_bytes, signature):
        logger.warning("Webhook signature verification failed")
        return Response(status_code=401, content="Invalid signature")

    try:
        import json
        payload = json.loads(payload_bytes)
    except Exception:
        return Response(status_code=400, content="Invalid JSON payload")

    # Dispatch asynchronously — GitHub expects a fast response
    from app.managers.webhook_dispatcher import WebhookDispatcher
    dispatcher = WebhookDispatcher()
    asyncio.create_task(dispatcher.dispatch(event_type, payload))

    return Response(status_code=200, content="OK")
