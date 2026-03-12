"""Tests for the health endpoint — no auth, no dependencies."""

import importlib
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


def _health_app():
    """Create a minimal app with just the health router, avoiding full import chain."""
    # Import the module directly, bypassing routes/__init__.py which pulls all deps
    mod = importlib.import_module("app.routes.health")
    app = FastAPI()
    app.include_router(mod.router)
    return app


@pytest.mark.anyio
async def test_health_returns_200():
    """GET /api/health should return 200 with status: healthy."""
    app = _health_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.anyio
async def test_health_method_not_allowed():
    """POST /api/health should return 405."""
    app = _health_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/health")

    assert response.status_code == 405
