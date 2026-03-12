"""
Authentication helpers for Qubiva routes.

Provides FastAPI dependency functions for authenticating HTTP requests,
WebSocket connections, and webhook callbacks.
"""

import os
import logging
import ipaddress
from urllib.parse import quote

from fastapi import Cookie, HTTPException, Query, Request, WebSocket, status

from app.deps import authenticator

logger = logging.getLogger("uvicorn.error")


async def authenticate_http_user(
    request: Request, session_token: str = Cookie(None, include_in_schema=False)
):
    # Check for internal service requests from runner Jobs via shared secret
    internal_api_key = os.getenv("INTERNAL_API_KEY")
    request_api_key = request.headers.get("X-Internal-Api-Key")
    if internal_api_key and request_api_key and request_api_key == internal_api_key:
        logger.debug("Internal service request authenticated via API key")
        return {"username": "internal_service", "projects": [], "org_roles": []}

    # Fallback: check pod/cluster CIDR for internal requests (K8s pod network)
    internal_cidr = os.getenv("INTERNAL_CIDR", os.getenv("VPC_CIDR"))
    if internal_cidr:
        forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = forwarded_for.split(",")[0] if forwarded_for else request.client.host
        if client_ip:
            try:
                if ipaddress.ip_address(client_ip) in ipaddress.ip_network(internal_cidr):
                    logger.debug(f"Internal request detected from {client_ip}")
                    return {"username": "internal_service", "projects": [], "org_roles": []}
            except ValueError:
                pass

    # Check for Bearer token in Authorization header first
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        user = await authenticator.get_current_user(token)
        if not user:
            # For Bearer token auth, always return 401 Unauthorized
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        return {
            "username": user.get("username"),
            "projects": user.get("projects", []),
            "org_roles": user.get("org_roles", []),
        }

    # Handle cookie-based auth for web requests
    if session_token:
        user = await authenticator.get_current_user(session_token)
        if user:
            return {
                "username": user.get("username"),
                "projects": user.get("projects", []),
                "org_roles": user.get("org_roles", []),
            }

    # If we reach here, authentication failed
    # For AJAX requests
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please login.",
        )

    # For regular web requests, redirect to login
    # Only preserve the original URL if it's not an API endpoint
    original_path = str(request.url.path)
    redirect_url = "/login"

    # Don't redirect back to API endpoints - only preserve dashboard/page URLs
    if not original_path.startswith("/api/"):
        original_url = original_path
        if request.url.query:
            original_url += f"?{request.url.query}"
        redirect_url = f"/login?next={quote(original_url)}"

    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER, headers={"Location": redirect_url}
    )


async def authenticate_webhook(
    request: Request,
    project_name: str,
    cloud_platform: str,
    account_id: str,
    token: str = Query(None),
):
    """
    Authentication specifically for cloud provider webhooks.

    Uses query parameter authentication (compatible with SNS/Azure/GCP webhooks)
    since cloud providers cannot send custom Authorization headers.

    This validates that:
    1. A token is provided in query parameter (?token=...)
    2. Token is a valid JWT
    3. Token has webhook scope (cannot be a user token)
    4. Token matches the URL parameters (project/platform/account)

    This prevents:
    - User tokens from being used on webhook endpoints
    - Webhook tokens from being used on other endpoints
    - Tokens from being used for wrong accounts
    """
    if not token:
        logger.warning(f"Webhook request missing authentication from {request.client.host}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook authentication token",
        )

    try:
        # Decode and verify JWT
        payload = authenticator.kms_manager.verify_jwt(token)

        # CRITICAL: Verify token is webhook-scoped
        if payload.get("token_type") != "webhook":
            logger.error(
                f"Non-webhook token used on webhook endpoint. Token type: {payload.get('token_type')}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid token type for webhook endpoint",
            )

        if payload.get("scope") != "cloud_alerts_webhook_only":
            logger.error(f"Token does not have webhook scope. Scope: {payload.get('scope')}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token does not have webhook scope",
            )

        # Verify token matches the URL parameters
        if (
            payload.get("project_name") != project_name
            or payload.get("cloud_platform") != cloud_platform.lower()
            or payload.get("account_id") != account_id
        ):
            logger.error(
                f"Token mismatch. Token: {payload.get('project_name')}/{payload.get('cloud_platform')}/{payload.get('account_id')} "
                f"vs URL: {project_name}/{cloud_platform}/{account_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token does not match webhook target",
            )

        logger.info(
            f"Webhook authenticated successfully for {project_name}/{cloud_platform}/{account_id}"
        )
        return {
            "webhook_auth": True,
            "project_name": project_name,
            "cloud_platform": cloud_platform,
            "account_id": account_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook authentication failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook token",
        )


async def authenticate_websocket_user(websocket: WebSocket):
    internal_service_discovery_host = os.getenv(
        "QUBIVA_API_ENDPOINT", ""
    )  # Default to an empty string
    request_host = websocket.headers.get("Host") or websocket.headers.get(
        "X-Forwarded-Host", ""
    )

    if (
        internal_service_discovery_host
        and request_host
        and internal_service_discovery_host in request_host
    ):
        # Skip authentication for internal calls only when both conditions are met
        logger.debug("Internal WebSocket request detected, skipping authentication.")
        return {
            "username": "internal_service",
            "projects": [],  # No project-specific restrictions for internal service calls
            "org_roles": [],  # No org-specific roles for internal service calls
        }

    # Proceed with regular WebSocket authentication for external users
    cookies = websocket.cookies
    if "session_token" not in cookies:
        raise HTTPException(status_code=400, detail="No session token provided")

    session_token = cookies["session_token"]
    user = await authenticator.get_current_user(session_token)
    if not user:
        logger.debug("Failed to authenticate WebSocket user, redirecting to login")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )

    return {
        "username": user.get("username"),
        "projects": user.get("projects", []),
        "org_roles": user.get("org_roles", []),
    }
