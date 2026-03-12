"""
Shared test fixtures for Qubiva.

Creates a FastAPI test client with mocked dependencies so tests can run
without MongoDB, K8s, or any external services.
"""

import os
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Set env vars BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "mongodb://localhost:27017/qubiva_test?directConnection=true")
os.environ.setdefault("LOCAL_ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleQ==")
os.environ.setdefault("LOCAL_SIGNING_KEY", "test-signing-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-api-key")
os.environ.setdefault("K8S_NAMESPACE", "default")
os.environ.setdefault("ARTIFACTS_STORAGE_PATH", "/tmp/artifacts")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(scope="session")
def internal_api_key():
    """The internal API key used for runner auth bypass."""
    return os.environ["INTERNAL_API_KEY"]


@pytest.fixture
def auth_headers(internal_api_key):
    """Headers that bypass authentication via internal API key."""
    return {"X-Internal-Api-Key": internal_api_key}


@pytest.fixture
def test_user():
    """Standard test user dict matching authenticate_http_user return format."""
    return {
        "username": "testuser@example.com",
        "projects": ["test-project"],
        "org_roles": ["org_admin"],
    }


@pytest.fixture
def mock_authenticate(test_user):
    """Patch authenticate_http_user to return test_user without actual auth."""
    with patch("app.auth_helpers.authenticate_http_user") as mock_auth:
        mock_auth.return_value = test_user
        yield mock_auth
