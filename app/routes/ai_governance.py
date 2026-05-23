"""
AI Governance API routes.

Exposes LiteLLM proxy management to the Qubiva dashboard.
Qubiva RBAC (org_admin required) is enforced at this layer;
the gateway itself is an internal service not reachable by end users.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.deps import ai_gateway_manager, audit_logger
from app.auth_helpers import authenticate_http_user

router = APIRouter(prefix="/api/v1/ai-governance", tags=["ai-governance"])


def _require_org_admin(user: dict):
    org_roles = user.get("org_roles") or []
    if "org_admin" not in org_roles:
        raise HTTPException(status_code=403, detail="org_admin role required")


def _gateway_error(exc: Exception):
    return HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(user: dict = Depends(authenticate_http_user)):
    """Return gateway enabled state and health."""
    return await ai_gateway_manager.get_status()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@router.get("/providers")
async def list_providers(user: dict = Depends(authenticate_http_user)):
    """Return the configured provider list with field schemas for the UI."""
    _require_org_admin(user)
    cfg = ai_gateway_manager._get_config()
    return {"providers": cfg.get("providers", [])}


# ---------------------------------------------------------------------------
# LLM provider credentials
# ---------------------------------------------------------------------------

class StoreCredentialRequest(BaseModel):
    name: str                          # human label, e.g. "prod-openai"
    provider: str                      # "openai" | "anthropic" | "vertex_ai" | etc.
    credential_values: Dict[str, Any]  # field-id → value from provider schema


class RotateCredentialRequest(BaseModel):
    credential_values: Dict[str, Any]  # field-id → new value from provider schema


@router.get("/credentials")
async def list_credentials(user: dict = Depends(authenticate_http_user)):
    """List stored LLM provider credentials (keys never exposed)."""
    _require_org_admin(user)
    try:
        return {"credentials": await ai_gateway_manager.list_credentials()}
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.post("/credentials", status_code=201)
async def store_credential(
    body: StoreCredentialRequest,
    user: dict = Depends(authenticate_http_user),
):
    """Store an LLM provider API key encrypted in Qubiva."""
    _require_org_admin(user)
    try:
        credential_id = await ai_gateway_manager.store_credential(
            name=body.name,
            provider=body.provider,
            credential_values=body.credential_values,
            acting_user=user["username"],
        )
        await audit_logger.log_event(
            "store_llm_credential", user["username"], "llm_credential", body.name
        )
        return {"credential_id": credential_id, "name": body.name, "provider": body.provider}
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.put("/credentials/{credential_id}")
async def rotate_credential(
    credential_id: str,
    body: RotateCredentialRequest,
    user: dict = Depends(authenticate_http_user),
):
    """Rotate an LLM provider API key and sync to all bound models."""
    _require_org_admin(user)
    try:
        result = await ai_gateway_manager.rotate_credential(
            credential_id=credential_id,
            credential_values=body.credential_values,
            acting_user=user["username"],
        )
        await audit_logger.log_event(
            "rotate_llm_credential", user["username"], "llm_credential", credential_id
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Delete a stored LLM provider credential."""
    _require_org_admin(user)
    try:
        deleted = await ai_gateway_manager.delete_credential(credential_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Credential not found")
        await audit_logger.log_event(
            "delete_llm_credential", user["username"], "llm_credential", credential_id
        )
        return {"deleted": True}
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise _gateway_error(exc)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AddModelRequest(BaseModel):
    model_name: str
    litellm_params: Dict[str, Any]
    model_info: Optional[Dict[str, Any]] = None
    # If set, api_key is resolved from the Qubiva credential store instead
    # of being embedded in litellm_params. Enables rotation sync.
    credential_id: Optional[str] = None


@router.get("/models")
async def list_models(user: dict = Depends(authenticate_http_user)):
    """List all models configured in the gateway."""
    _require_org_admin(user)
    try:
        return {"models": await ai_gateway_manager.list_models()}
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.post("/models")
async def add_model(
    body: AddModelRequest,
    user: dict = Depends(authenticate_http_user),
):
    """Add a new model to the gateway.

    Supply either litellm_params.api_key directly, or credential_id to
    resolve the key from Qubiva's encrypted credential store (recommended —
    enables automatic key rotation sync).
    """
    _require_org_admin(user)
    try:
        if body.credential_id:
            result = await ai_gateway_manager.add_model_with_credential(
                model_name=body.model_name,
                litellm_params=body.litellm_params,
                credential_id=body.credential_id,
                model_info=body.model_info,
            )
        else:
            params: Dict[str, Any] = {
                "model_name": body.model_name,
                "litellm_params": body.litellm_params,
            }
            if body.model_info:
                params["model_info"] = body.model_info
            result = await ai_gateway_manager.add_model(params)

        await audit_logger.log_event(
            "add_ai_model", user["username"], "ai_model", body.model_name
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Delete a model from the gateway."""
    _require_org_admin(user)
    try:
        result = await ai_gateway_manager.delete_model(model_id)
        await audit_logger.log_event(
            "delete_ai_model", user["username"], "ai_model", model_id
        )
        return result
    except RuntimeError as exc:
        raise _gateway_error(exc)


# ---------------------------------------------------------------------------
# Virtual keys
# ---------------------------------------------------------------------------

class CreateKeyRequest(BaseModel):
    alias: Optional[str] = None
    # key_type: "project" (scoped to a project) or "user" (scoped to a specific user)
    key_type: Optional[str] = None
    project_name: Optional[str] = None    # required when key_type == "project"
    owner_username: Optional[str] = None  # required when key_type == "user"
    models: Optional[List[str]] = None
    max_budget: Optional[float] = None
    budget_duration: Optional[str] = None   # "monthly" | "daily"
    rpm_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class UpdateKeyRequest(BaseModel):
    max_budget: Optional[float] = None
    budget_duration: Optional[str] = None
    rpm_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    models: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@router.get("/keys")
async def list_keys(user: dict = Depends(authenticate_http_user)):
    """List all virtual keys."""
    _require_org_admin(user)
    try:
        return {"keys": await ai_gateway_manager.list_keys()}
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.post("/keys")
async def create_key(
    body: CreateKeyRequest,
    user: dict = Depends(authenticate_http_user),
):
    """Create a virtual key with optional budget, rate limits, and owner binding.

    key_type "project": key is scoped to a project (team_id = project_name).
    key_type "user":    key is scoped to a specific user (user_id = owner_username).
    """
    _require_org_admin(user)
    try:
        # Strip RBAC-only fields before forwarding to LiteLLM
        excluded = {"key_type", "project_name", "owner_username"}
        params = {k: v for k, v in body.model_dump(exclude_none=True).items() if k not in excluded}
        result = await ai_gateway_manager.create_key(
            params=params,
            key_type=body.key_type,
            project_name=body.project_name,
            owner_username=body.owner_username,
            created_by=user["username"],
        )
        await audit_logger.log_event(
            "create_ai_key", user["username"], "ai_key", body.alias or "unnamed"
        )
        return result
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.patch("/keys/{key_id}")
async def update_key(
    key_id: str,
    body: UpdateKeyRequest,
    user: dict = Depends(authenticate_http_user),
):
    """Update budget or rate limits on a virtual key."""
    _require_org_admin(user)
    try:
        params = body.model_dump(exclude_none=True)
        result = await ai_gateway_manager.update_key(key_id, params)
        await audit_logger.log_event(
            "update_ai_key", user["username"], "ai_key", key_id
        )
        return result
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.delete("/keys/{key_id}")
async def delete_key(
    key_id: str,
    user: dict = Depends(authenticate_http_user),
):
    """Delete a virtual key."""
    _require_org_admin(user)
    try:
        result = await ai_gateway_manager.delete_key(key_id)
        await audit_logger.log_event(
            "delete_ai_key", user["username"], "ai_key", key_id
        )
        return result
    except RuntimeError as exc:
        raise _gateway_error(exc)


# ---------------------------------------------------------------------------
# Spend / usage
# ---------------------------------------------------------------------------

@router.get("/spend")
async def get_spend_summary(user: dict = Depends(authenticate_http_user)):
    """Return spend summary: global total + per-key + per-model breakdowns."""
    _require_org_admin(user)
    try:
        return await ai_gateway_manager.get_spend_summary()
    except RuntimeError as exc:
        raise _gateway_error(exc)


@router.get("/spend/logs")
async def get_spend_logs(
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    start_date: str = Query(None),
    end_date: str = Query(None),
    user: dict = Depends(authenticate_http_user),
):
    """Return detailed LLM call logs with per-request cost data."""
    _require_org_admin(user)
    try:
        logs = await ai_gateway_manager.get_spend_logs(
            limit=limit, offset=offset, start_date=start_date, end_date=end_date
        )
        return {"logs": logs, "limit": limit, "offset": offset}
    except RuntimeError as exc:
        raise _gateway_error(exc)
