"""Tests for authentication flows."""

import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, Depends


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _make_app():
    """Create a minimal app with auth-protected routes for testing."""
    from app.routes.health import router as health_router
    from app.auth_helpers import authenticate_http_user

    app = FastAPI()
    app.include_router(health_router)

    # Add a test-only protected endpoint
    @app.get("/api/test/whoami")
    async def whoami(user: dict = Depends(authenticate_http_user)):
        return {"username": user["username"], "org_roles": user.get("org_roles", [])}

    return app


@pytest.mark.anyio
async def test_internal_api_key_auth():
    """Requests with valid X-Internal-Api-Key should authenticate as internal_service."""
    app = _make_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/test/whoami",
            headers={"X-Internal-Api-Key": os.environ["INTERNAL_API_KEY"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "internal_service"


@pytest.mark.anyio
async def test_invalid_api_key_rejected():
    """Requests with a wrong X-Internal-Api-Key should not bypass auth."""
    app = _make_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/test/whoami",
            headers={
                "X-Internal-Api-Key": "wrong-key",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    # Should be 401 (no valid auth method, AJAX request)
    assert response.status_code == 401


@pytest.mark.anyio
async def test_no_auth_returns_401_for_ajax():
    """AJAX requests without any auth should get 401."""
    app = _make_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/test/whoami",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_no_auth_redirects_for_browser():
    """Browser requests (no Accept: application/json) should redirect to login."""
    app = _make_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        response = await client.get("/api/test/whoami")

    # Should redirect to login
    assert response.status_code == 303
    assert "/login" in response.headers.get("location", "")


@pytest.mark.anyio
async def test_bearer_token_auth():
    """Valid bearer token should authenticate the user."""
    app = _make_app()
    transport = ASGITransport(app=app)

    mock_user = {
        "username": "bearer@test.com",
        "projects": [],
        "org_roles": ["org_admin"],
    }

    with patch("app.auth_helpers.authenticator") as mock_authenticator:
        mock_authenticator.get_current_user = AsyncMock(return_value=mock_user)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/test/whoami",
                headers={"Authorization": "Bearer test-token-123"},
            )

    assert response.status_code == 200
    assert response.json()["username"] == "bearer@test.com"
