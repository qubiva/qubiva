"""
Internal runner callback routes for Qubiva.

Endpoints called by Terraform/Discovery runner Jobs via HTTP.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_request_tracker
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.request_manager import RequestTracker
from app.app_config_manager import ConfigManager

router = APIRouter()


@router.post("/api/internal/v1/update_request_state/{request_id}")
async def update_request_state(
    request_id: str,
    request: Models.UpdateStateRequest,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
):
    # Update the request state in the database
    success, message = await tracker.update_request_state(request_id, request.state)

    if not success:
        # If update fails, raise an HTTP exception with a 400 status code
        raise HTTPException(status_code=400, detail=message)

    # Return a success message on successful state update
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
    # Update the request state in the database
    success, message = await tracker.update_error_details(request_id, request.error_message)

    if not success:
        # If update fails, raise an HTTP exception with a 400 status code
        raise HTTPException(status_code=400, detail=message)

    # Return a success message on successful state update
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
    """
    Internal endpoint for discovery runner to fetch discovery configuration.
    This avoids passing large queries via Fargate environment variables.
    """
    success, result = await tracker.get_discovery_config(request_id)

    if not success:
        raise HTTPException(status_code=404, detail=result)

    return {
        "status": "success",
        "discovery_config": result
    }


@router.post("/api/internal/v1/reload-config")
async def reload_config(
    user: dict = Depends(authenticate_http_user),
):
    """Trigger an immediate config reload from disk.

    Useful after a ConfigMap update to avoid waiting for the periodic sync.
    Fires registered on_change callbacks if any top-level keys changed.
    """
    config_manager = ConfigManager()
    success = await config_manager.sync_config()

    if not success:
        raise HTTPException(status_code=500, detail="Config reload failed")

    return {
        "status": "success",
        "message": "Configuration reloaded",
    }
