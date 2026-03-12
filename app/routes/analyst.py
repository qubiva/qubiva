"""
Cloud Analyst (AI chat) routes for Qubiva.

Conversations, messages (SSE streaming), schema search, session status, and restart.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from app.deps import (
    project_manager,
    rbac,
    chat_manager,
    session_manager,
    schema_registry,
    ConfigManager,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/api/v1/analyst/accessible-projects")
async def get_analyst_accessible_projects(
    request: Request,
    user: dict = Depends(authenticate_http_user),
):
    """Return projects and cloud accounts the user has access to.

    Used by the analyst UI to populate the project/scope picker.
    RBAC-filtered: only projects where user has analyst permission.
    """
    username = user["username"]
    org_roles = user.get("org_roles") or []
    is_org_admin = "org_admin" in org_roles
    try:
        # Get project details for user (respects membership)
        success, project_details = await project_manager.get_project_details_for_projects(
            username, project_names=None, is_org_user=is_org_admin,
        )
        # Check org-level analyst access early so all return paths include it
        has_org_analyst = is_org_admin
        if not has_org_analyst and rbac:
            has_org_analyst, _ = rbac.check_permissions(
                ["org_analyst_use"], [], org_roles
            )

        if not success or not project_details:
            return {"projects": [], "org_analyst_access": has_org_analyst}

        accessible = []
        for proj_name in project_details:
            # Check analyst permission (org admins bypass)
            if not is_org_admin:
                user_roles = await project_manager.get_user_roles_by_project(username, proj_name)
                user_perms = rbac.get_permissions_for_roles(user_roles) if user_roles else []
                if "project_analyst_use" not in user_perms:
                    continue

            # Get cloud accounts for this project
            accounts_raw = await project_manager.get_cloud_accounts_by_project_name(proj_name)
            accounts = []
            if isinstance(accounts_raw, tuple):
                ok, data = accounts_raw
                if ok and isinstance(data, list):
                    accounts = data
            elif isinstance(accounts_raw, list):
                accounts = accounts_raw

            cloud_accounts = [
                {
                    "account_id": a.get("account_id"),
                    "cloud_platform": a.get("cloud_platform"),
                    "alias": a.get("alias", ""),
                }
                for a in accounts
            ]

            accessible.append({
                "project_name": proj_name,
                "cloud_accounts": cloud_accounts,
            })

        return {
            "projects": accessible,
            "org_analyst_access": has_org_analyst,
        }
    except Exception as e:
        logger.error(f"Failed to get accessible projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/analyst/conversations")
async def create_analyst_conversation(
    request: Request,
    body: Models.AnalystConversationCreate,
    user: dict = Depends(authenticate_http_user),
):
    """Create a new analyst conversation and start a query session pod."""
    analyst_config = ConfigManager.get_config("cloud_analyst") or {}
    if not analyst_config.get("enabled", False):
        raise HTTPException(status_code=503, detail="Cloud Analyst is not enabled")

    try:
        conversation_id = await chat_manager.create_conversation(
            user=user["username"],
            project_name=body.project_name,
            cloud_platform=body.cloud_platform,
            account_id=body.account_id,
            scope=body.scope,
            org_roles=user.get("org_roles") or [],
        )
        return {"conversation_id": conversation_id, "status": "created"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create analyst conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/analyst/conversations/{conversation_id}/messages")
async def send_analyst_message(
    request: Request,
    conversation_id: str,
    body: Models.AnalystMessageRequest,
    user: dict = Depends(authenticate_http_user),
):
    """Send a message and stream the AI response via SSE."""

    async def event_generator():
        try:
            async for event in chat_manager.send_message(
                conversation_id=conversation_id,
                user_message=body.message,
                user=user["username"],
                org_roles=user.get("org_roles") or [],
            ):
                data = json.dumps(event.data)
                yield f"event: {event.type}\ndata: {data}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/v1/analyst/conversations")
async def list_analyst_conversations(
    request: Request,
    project_name: Optional[str] = None,
    scope: Optional[str] = None,
    user: dict = Depends(authenticate_http_user),
):
    """List conversations for the current user."""
    convs = await chat_manager.list_conversations(
        user=user["username"],
        project_name=project_name,
        scope=scope,
    )
    return {"conversations": convs}


@router.get("/api/v1/analyst/conversations/{conversation_id}")
async def get_analyst_conversation(
    request: Request,
    conversation_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Get full conversation history."""
    conv = await chat_manager.get_conversation_history(
        conversation_id=conversation_id,
        user=user["username"],
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/api/v1/analyst/conversations/{conversation_id}")
async def delete_analyst_conversation(
    request: Request,
    conversation_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Delete a conversation and destroy its session pod."""
    success = await chat_manager.delete_conversation(
        conversation_id=conversation_id,
        user=user["username"],
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


@router.get("/api/v1/analyst/conversations/{conversation_id}/status")
async def get_analyst_session_status(
    request: Request,
    conversation_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Get the status of a conversation's query session pod."""
    status_val = await session_manager.get_session_status(conversation_id)
    error = await session_manager.get_session_error(conversation_id)
    return {"status": status_val, "error": error}


@router.post("/api/v1/analyst/conversations/{conversation_id}/restart")
async def restart_analyst_session(
    request: Request,
    conversation_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Restart the session pod for an existing conversation."""
    success = await chat_manager.restart_session(
        conversation_id=conversation_id,
        user=user["username"],
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "restarting"}


@router.get("/api/v1/analyst/schema/{platform}/search")
async def search_analyst_schema(
    request: Request,
    platform: str,
    q: str = "",
    user: dict = Depends(authenticate_http_user),
):
    """Search cloud table schemas by keyword."""
    if not q.strip():
        return {"tables": []}
    keywords = [k.strip() for k in q.split() if k.strip()]
    results = schema_registry.search_tables(platform, keywords, limit=20)
    return {"tables": results}
