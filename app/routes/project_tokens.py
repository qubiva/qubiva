"""
Project token API routes.

Project tokens are identity-less JWTs scoped to a project, carrying project roles.
They are created by project admins (and org admins, who own everything) and used
by applications to authenticate against the AI governance gateway.

Access is gated on project-level permissions:
  project_token_create / project_token_list / project_token_revoke
  (all covered by project_token_* — held by project_token_user role and project_admin via project_*)
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth_helpers import authenticate_http_user
from app.deps import ai_gateway_manager, audit_logger, rbac
from app.decorators import permissions

router = APIRouter(prefix="/api/v1/projects/{project_name}/tokens", tags=["project-tokens"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateProjectTokenRequest(BaseModel):
    token_name: str
    roles: List[str]
    expiry_days: int = 90  # 1–365 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_expiry(days: int):
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="expiry_days must be between 1 and 365")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
@permissions(["project_token_create"])
async def create_project_token(
    project_name: str,
    body: CreateProjectTokenRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Create a project token with assigned roles.

    The raw token value is returned once only — store it securely.
    """
    _validate_expiry(body.expiry_days)

    # Validate requested roles exist in the RBAC config
    valid_roles = set(rbac.get_all_project_roles())
    invalid = [r for r in body.roles if r not in valid_roles]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown project roles: {invalid}. Valid roles: {sorted(valid_roles)}",
        )

    try:
        result = await ai_gateway_manager.create_project_token(
            project_name=project_name,
            token_name=body.token_name,
            roles=body.roles,
            expiry_hours=body.expiry_days * 24,
            created_by=user["username"],
        )
        await audit_logger.log_event(
            "create_project_token", user["username"], "project_token", body.token_name,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("")
@permissions(["project_token_list"])
async def list_project_tokens(
    project_name: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """List active project tokens (metadata only, no token values)."""
    try:
        tokens = await ai_gateway_manager.list_project_tokens(project_name)
        return {"tokens": tokens}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.delete("/{token_id}")
@permissions(["project_token_revoke"])
async def revoke_project_token(
    project_name: str,
    token_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Revoke a project token immediately."""
    try:
        revoked = await ai_gateway_manager.revoke_project_token(project_name, token_id)
        if not revoked:
            raise HTTPException(status_code=404, detail="Token not found or already revoked")
        await audit_logger.log_event(
            "revoke_project_token", user["username"], "project_token", token_id,
        )
        return {"revoked": True}
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
