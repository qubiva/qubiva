"""
Internal routes for Qubiva.

Endpoints called by Terraform/Discovery runner Jobs and the AI gateway auth hook via HTTP.
"""

import base64
import ipaddress
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.deps import (
    ai_gateway_manager,
    db_manager,
    kms_manager,
    project_manager,
    rbac,
    get_request_tracker,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.request_manager import RequestTracker
from app.app_config_manager import ConfigManager

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal-caller guard (used by validate-token — called by LiteLLM, not users)
# ---------------------------------------------------------------------------

def _is_internal_caller(request: Request) -> bool:
    """Return True if the request originates from within the cluster."""
    internal_api_key = os.getenv("INTERNAL_API_KEY")
    if internal_api_key and request.headers.get("X-Internal-Api-Key") == internal_api_key:
        return True
    internal_cidr = os.getenv("INTERNAL_CIDR", os.getenv("VPC_CIDR", ""))
    if internal_cidr:
        forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (
            request.client.host if request.client else ""
        )
        try:
            if client_ip and ipaddress.ip_address(client_ip) in ipaddress.ip_network(internal_cidr):
                return True
        except ValueError:
            pass
    return False


# ---------------------------------------------------------------------------
# Token validation endpoint (called by LiteLLM custom auth hook)
# ---------------------------------------------------------------------------

class ValidateTokenRequest(BaseModel):
    token: str        # Qubiva token: user API JWT or project token JWT
    virtual_key: str  # LiteLLM virtual key (sk-...)


@router.post("/api/v1/internal/validate-token")
async def validate_token(body: ValidateTokenRequest, request: Request):
    """
    Validate a Qubiva identity token against a LiteLLM virtual key.

    Called exclusively by the LiteLLM proxy custom auth hook.
    Returns 200 with identity info on success, 401/403 on failure.

    Auth rules:
      - Key bound to a project: token must belong to the same project (project token)
        OR be a user token for a member with project_ai_key_use permission.
      - Key bound to a user: token must be a user token for that same user.
      - Key with no Qubiva binding: any valid Qubiva token is accepted.
    """
    if not _is_internal_caller(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal endpoint only")

    # Step 1: Verify the Qubiva token JWT
    try:
        payload = kms_manager.verify_jwt(body.token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    token_type = payload.get("token_type")
    is_project_token = token_type == "project_token"

    # Step 2: Look up virtual key binding
    binding = await ai_gateway_manager.get_key_binding(body.virtual_key)

    # Step 3: Validate identity vs. binding
    if binding is None:
        # No binding: accept any valid Qubiva token, return identity
        if is_project_token:
            return {
                "valid": True,
                "token_type": "project",
                "project_name": payload.get("project_name"),
                "username": None,
            }
        return {
            "valid": True,
            "token_type": "user",
            "project_name": None,
            "username": payload.get("sub"),
        }

    key_type = binding["key_type"]

    if is_project_token:
        # Project token path
        token_id = payload.get("token_id")
        token_project = payload.get("project_name")
        token_roles = payload.get("roles", [])

        if not token_id or not token_project:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed project token")

        # Confirm not revoked
        active = await ai_gateway_manager.validate_project_token_id(token_id, token_project)
        if not active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Project token revoked or expired")

        if key_type == "project":
            if token_project != binding.get("project_name"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Project token does not match the key's bound project",
                )
            permitted, _ = rbac.check_permissions(["project_ai_key_use"], token_roles, [])
            if not permitted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Project token lacks project_ai_key_use permission",
                )
        else:
            # key_type == "user" — project tokens cannot use user-bound keys
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project tokens cannot use user-bound AI keys",
            )

        return {
            "valid": True,
            "token_type": "project",
            "project_name": token_project,
            "username": None,
        }

    else:
        # User token path
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed user token")

        # Reject non-user token types
        if token_type in ("webhook", "project_token"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token type")

        # Fetch user to get org_roles and active status
        user_doc = await db_manager.find_document("users", {"username": username})
        if not user_doc or not user_doc.get("active", True):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

        org_roles = user_doc.get("org_roles", [])

        if key_type == "user":
            if username != binding.get("owner_username"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token identity does not match the key's bound user",
                )
        elif key_type == "project":
            bound_project = binding.get("project_name")
            success, project_roles = await project_manager.get_user_roles_by_project(
                username=username,
                project_name=bound_project,
                is_org_user=bool(org_roles),
            )
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User is not a member of project '{bound_project}'",
                )
            permitted, _ = rbac.check_permissions(["project_ai_key_use"], project_roles, org_roles)
            if not permitted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User lacks project_ai_key_use permission for this project",
                )

        return {
            "valid": True,
            "token_type": "user",
            "project_name": binding.get("project_name"),
            "username": username,
        }


# ---------------------------------------------------------------------------
# Runner callback routes
# ---------------------------------------------------------------------------

def _extract_plan_summary(plan_output: str) -> str:
    """Extract a brief resource diff summary from terraform plan output."""
    if not plan_output:
        return "Plan completed. Review the output before approving."
    import re
    match = re.search(r"Plan: (\d+ to add, \d+ to change, \d+ to destroy)", plan_output, re.IGNORECASE)
    if match:
        return f"Plan complete: {match.group(1)}. Review and approve to apply."
    return "Plan completed. Review the output before approving."


async def _maybe_update_check_run(request_id: str, new_state: str, plan_output: str = ""):
    """If the request has a GitHub Check Run attached, update it to reflect the new state."""
    try:
        doc = await db_manager.find_document("requests", {"request_id": request_id})
        if not doc:
            return
        check_run_id = doc.get("check_run_id")
        repo_full_name = doc.get("check_run_repo")
        if not check_run_id or not repo_full_name:
            return

        state_map = {
            "in progress":       ("in_progress", None,               "In Progress",         "Terraform plan is running."),
            "planned":           ("completed",   "action_required",  "Awaiting Approval",   _extract_plan_summary(plan_output or doc.get("plan_output", ""))),
            "completed":         ("completed",   "success",          "Apply Succeeded",     "Infrastructure changes applied successfully."),
            "execution failed":  ("completed",   "failure",          "Execution Failed",    doc.get("error_details", "Execution failed.")),
            "timed out":         ("completed",   "failure",          "Timed Out",           "Runner exceeded timeout."),
            "rejected":          ("completed",   "cancelled",        "Plan Rejected",       "Plan was rejected by a team member."),
            "approval_timed_out":("completed",   "cancelled",        "Approval Timed Out",  "No approval received within the timeout period."),
        }
        if new_state not in state_map:
            return
        status, conclusion, title, summary = state_map[new_state]
        await project_manager.update_check_run(
            repo_full_name=repo_full_name,
            check_run_id=check_run_id,
            status=status,
            conclusion=conclusion,
            title=title,
            summary=summary,
        )
    except Exception as exc:
        logger.debug("Check run update failed for %s state=%s: %s", request_id, new_state, exc)


@router.post("/api/internal/v1/update_request_state/{request_id}")
async def update_request_state(
    request_id: str,
    request: Models.UpdateStateRequest,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    success, message = await tracker.update_request_state(request_id, request.state)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    # Update GitHub Check Run if applicable (fire-and-forget)
    import asyncio
    asyncio.create_task(_maybe_update_check_run(request_id, request.state))
    return {
        "status": "success",
        "message": f"Request {request_id} updated to state: {request.state}",
    }


@router.post("/api/internal/v1/update_request_error_details/{request_id}")
async def update_request_error_details(
    request_id: str,
    request: Models.UpdateErrorDetailsRequest,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    success, message = await tracker.update_error_details(request_id, request.error_message)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "status": "success",
        "message": f"Request {request_id} updated with error message: {request.error_message}",
    }


@router.get("/api/internal/v1/requests/{request_id}/discovery_config")
async def get_discovery_config(
    request_id: str,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    """Internal endpoint for discovery runner to fetch discovery configuration."""
    success, result = await tracker.get_discovery_config(request_id)
    if not success:
        raise HTTPException(status_code=404, detail=result)
    return {
        "status": "success",
        "discovery_config": result,
    }


class PlanArtifactUpload(BaseModel):
    plan_output: str   # Captured text from `terraform plan`
    plan_binary_b64: str = ""  # Base64-encoded .tfplan binary (may be empty if runner skips)
    plan_summary: dict = {}  # Structured resource change counts from `terraform show -json`


@router.post("/api/internal/v1/requests/{request_id}/plan_artifact")
async def upload_plan_artifact(
    request_id: str,
    body: PlanArtifactUpload,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    """Runner uploads plan output text and optional plan binary after terraform plan completes."""
    from app.managers.plan_store import PlanStore
    store = PlanStore()

    # Store plan text and structured summary in the request document
    fields = {"plan_output": body.plan_output}
    if body.plan_summary:
        fields["plan_summary"] = body.plan_summary
    await tracker.update_request_fields(request_id, fields)

    # Store plan binary to filesystem (if provided)
    if body.plan_binary_b64:
        try:
            store.save_plan_binary(request_id, body.plan_binary_b64)
        except Exception as exc:
            logger.warning("Failed to save plan binary for %s: %s", request_id, exc)

    return {"status": "success", "message": "Plan artifact stored"}


@router.get("/api/internal/v1/requests/{request_id}/plan_artifact")
async def download_plan_artifact(
    request_id: str,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    """Apply runner downloads the saved plan binary for this request."""
    from app.managers.plan_store import PlanStore
    store = PlanStore()

    if not store.has_plan_binary(request_id):
        raise HTTPException(status_code=404, detail=f"No plan binary found for request {request_id}")

    binary = store.get_plan_binary(request_id)
    return Response(
        content=binary,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="tfplan.bin"'},
    )


class RunMetadataUpdate(BaseModel):
    head_sha: str = ""
    head_commit_url: str = ""


@router.post("/api/internal/v1/requests/{request_id}/run_metadata")
async def update_run_metadata(
    request_id: str,
    body: RunMetadataUpdate,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    """Runner reports commit SHA and URL after clone so manual runs show commit info."""
    fields = {}
    if body.head_sha:
        fields["head_sha"] = body.head_sha
    if body.head_commit_url:
        fields["head_commit_url"] = body.head_commit_url
    if fields:
        await tracker.update_request_fields(request_id, fields)
    return {"status": "success"}


@router.post("/api/internal/v1/reload-config")
async def reload_config(
    user: dict = Depends(authenticate_http_user),
):
    """Trigger an immediate config reload from disk."""
    config_manager = ConfigManager()
    success = await config_manager.sync_config()
    if not success:
        raise HTTPException(status_code=500, detail="Config reload failed")
    return {
        "status": "success",
        "message": "Configuration reloaded",
    }
