"""
Authentication routes for Qubiva.

Covers login, logout, session management, API tokens, and password reset.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse, JSONResponse

from app.deps import (
    authenticator,
    project_manager,
    sso_manager,
    templates,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# ---- Page routes ----

@router.get("/")
async def root_redirect():
    return RedirectResponse(url="/dashboard")


@router.get("/login")
async def login(request: Request, response: Response, next: str = None):
    # Check if SSO is enabled (only if SSO manager is available)
    sso_enabled = False
    if sso_manager is not None:
        try:
            sso_enabled = await sso_manager.is_sso_enabled()
        except Exception as e:
            logger.debug(f"SSO check failed: {e}")
            sso_enabled = False

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "sso_enabled": sso_enabled,
            "next_url": next
        }
    )


@router.get("/enable-password-reset")
async def forgot_password(request: Request, response: Response):
    return templates.TemplateResponse(
        "enable_password_reset.html", {"request": request}
    )


@router.get("/reset-password")
async def reset_password(request: Request, response: Response):
    return templates.TemplateResponse("reset_password.html", {"request": request})


# ---- API routes ----

@router.post("/api/v1/web-login")
async def web_login(request: Request, credentials: Models.LoginData, response: Response):
    user = await authenticator.authenticate_user(
        credentials.username, credentials.password
    )
    if not user:
        return JSONResponse(
            status_code=401, content={"message": "Invalid username or password"}
        )
    token = authenticator.create_access_token(credentials.username)
    response.set_cookie(
        key="session_token", value=token, httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )

    # Validate and sanitize the redirect URL for security
    redirect_url = "/dashboard"  # Default
    if credentials.next:
        from urllib.parse import urlparse
        parsed = urlparse(credentials.next)
        if (credentials.next.startswith("/")
                and not credentials.next.startswith("//")
                and not parsed.scheme and not parsed.netloc
                and "\\" not in credentials.next):
            redirect_url = credentials.next

    return {"message": "Login successful", "redirect_url": redirect_url}


@router.get("/api/v1/api-tokens/list")
async def list_api_tokens(user: dict = Depends(authenticate_http_user)):
    # Fetch the user's document
    user_doc = await authenticator.db_manager.find_document(
        authenticator.user_collection_name, {"username": user["username"]}
    )
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    # Return token metadata or an empty list
    api_tokens = user_doc.get("api_tokens", [])
    if not api_tokens:
        return {"message": "No API tokens found.", "api_tokens": []}

    from datetime import datetime, timedelta

    token_list = []
    for t in api_tokens:
        created_str = t.get("created_at", "")
        expiry_hours = t.get("expiry_hours", 0)
        expires_at = None
        expired = False
        if created_str and expiry_hours:
            try:
                created_dt = datetime.fromisoformat(created_str)
                expires_dt = created_dt + timedelta(hours=expiry_hours)
                expires_at = expires_dt.isoformat()
                expired = datetime.utcnow() > expires_dt
            except (ValueError, TypeError):
                pass
        token_list.append({
            "token_name": t["token_name"],
            "created_at": created_str,
            "expires_at": expires_at,
            "expired": expired,
        })

    return {"api_tokens": token_list}


@router.post("/api/v1/api-tokens/generate")
async def generate_api_token(
    request: Models.GenerateTokenRequest, user: dict = Depends(authenticate_http_user)
):
    # Convert days to hours if needed
    if request.expiry_days:
        expiry = request.expiry_days * 24
    else:
        expiry = request.expiry_hours

    success, msg = await authenticator.create_api_token(
        username=user["username"],
        expiry=expiry,
        token_name=request.token_name,
    )

    if success:
        return {"message": msg, "api_token": msg}  # Include token in success response
    else:
        raise HTTPException(status_code=400, detail=msg)  # Propagate error message


@router.post("/api/v1/api-tokens/revoke")
async def revoke_api_token(
    request: Models.RevokeTokenRequest, user: dict = Depends(authenticate_http_user)
):
    success, msg = await authenticator.revoke_api_token(
        username=user["username"],
        token_name=request.token_name,
    )

    if success:
        return {"message": msg}
    else:
        raise HTTPException(status_code=400, detail=msg)


@router.post("/api/v1/web-logout")
def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


@router.post("/api/v1/session/renew")
async def renew_session(
    request: Request,
    response: Response,
    session_token: str = Cookie(None, include_in_schema=False),
):
    """
    Renew the current session by issuing a new token.
    Maximum of 3 renewals allowed per session.
    """
    MAX_RENEWALS = 3

    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active session to renew"
        )

    # Get full token payload to check renewal count and validity
    payload = authenticator.get_token_payload(session_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    username = payload.get("sub")
    current_renewal_count = payload.get("renewal_count", 0)

    # Check if max renewals exceeded
    if current_renewal_count >= MAX_RENEWALS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Maximum session renewals exceeded. Please log in again."
        )

    # Create new token with incremented renewal count
    new_token = authenticator.create_access_token(
        username=username,
        expiry_hours=1,
        renewal_count=current_renewal_count + 1
    )

    # Create response with JSON content
    json_response = JSONResponse(
        content={
            "message": "Session renewed successfully",
            "renewal_count": current_renewal_count + 1,
            "max_renewals": MAX_RENEWALS,
            "renewals_remaining": MAX_RENEWALS - (current_renewal_count + 1)
        }
    )

    # Set new cookie on the response
    json_response.set_cookie(
        key="session_token",
        value=new_token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/"
    )

    return json_response


@router.get("/api/v1/session/info")
async def get_session_info(
    session_token: str = Cookie(None, include_in_schema=False),
):
    """
    Get information about the current session including expiry and renewal count.
    """
    MAX_RENEWALS = 3

    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active session"
        )

    payload = authenticator.get_token_payload(session_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    # Calculate seconds remaining from server's perspective
    # IMPORTANT: Use datetime.utcnow().timestamp() to match how tokens are created in kms_manager.py
    current_time = int(datetime.utcnow().timestamp())
    expires_at = payload.get("exp")
    seconds_remaining = max(0, expires_at - current_time)

    return JSONResponse(
        content={
            "username": payload.get("sub"),
            "expires_at": expires_at,
            "issued_at": payload.get("iat"),
            "seconds_remaining": seconds_remaining,
            "renewal_count": payload.get("renewal_count", 0),
            "max_renewals": MAX_RENEWALS,
            "renewals_remaining": MAX_RENEWALS - payload.get("renewal_count", 0)
        }
    )


# ---- Password reset ----

@router.post("/api/v1/password/request-password-reset")
async def request_password_reset(data: Models.PasswordResetRequest):
    # Check if user exists and is local (not SSO)
    user_exists, user_data = await project_manager.user_exists(data.username)

    if user_exists:
        # User exists - check if SSO
        if user_data.get('auth_method') == 'sso':
            # SSO user - don't send email, but return generic message
            logger.warning(f"SSO user {data.username} attempted password reset")
            return {"message": "If your account exists, you will receive a password reset email."}

        # Local user - send reset email
        await project_manager.send_password_reset_email(data.username)

    # ALWAYS return the same message (whether user exists or not)
    return {"message": "If your account exists, you will receive a password reset email."}


@router.post("/api/v1/password/submit-new-password")
async def submit_new_password(
    data: Models.PasswordResetSubmit
):
    success, message = await project_manager.reset_password(
        data.token, data.new_password
    )
    if success:
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)
