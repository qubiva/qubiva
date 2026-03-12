"""
Stats and OpenAPI docs routes for Qubiva.
"""

import logging

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html

from app.deps import stats_provider
from app.models import Models
from app.auth_helpers import authenticate_http_user

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.post("/api/v1/stats/user")
async def get_global_stats(user_stats_request: Models.userStats):
    """
    Return some useful stats to display on Dashboard home.
    """
    try:
        stats = await stats_provider.get_user_dashboard_stats(user_stats_request.username)
        logger.debug(stats)
        # Check if stats exist
        if not stats:
            raise HTTPException(status_code=404, detail="No stats found.")

        return {"stats": stats}

    except Exception as e:
        logger.error(f"Failed to fetch stats: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal error occurred while fetching stats.")


@router.post("/api/v1/projects/{project_name}/stats")
async def get_project_stats(project_name: str, user_stats_request: Models.userStatsforProject):
    """
    Return some useful stats to display on Dashboard home.
    """
    try:
        stats = await stats_provider.get_project_overview(project_name, user_stats_request.username)
        logger.debug(stats)
        # Check if stats exist
        if not stats:
            raise HTTPException(status_code=404, detail="No stats found.")

        return {"stats": stats}

    except Exception as e:
        logger.error(f"Failed to fetch stats: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal error occurred while fetching stats.")


# Protected docs endpoint
@router.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html(user: dict = Depends(authenticate_http_user)):
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Qubiva API Documentation",
        swagger_favicon_url="/favicon.ico",
    )


# Protected OpenAPI schema endpoint
@router.get("/openapi.json", include_in_schema=False)
async def custom_openapi_schema(user: dict = Depends(authenticate_http_user)):
    from app.routes.stats import get_custom_openapi as _get_custom_openapi
    # We need a reference to the actual FastAPI app; import it lazily
    from app.app import app as _app
    return _get_custom_openapi(_app)


def get_custom_openapi(app: FastAPI):
    """
    Generate a custom OpenAPI schema that includes only endpoints matching specified patterns.
    """
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        routes=app.routes,
        title="Qubiva API v1",
        version="1.0.0",
        description=(
            "Welcome to the Qubiva API documentation. Here, you'll find details about all the available API endpoints. "
            "To interact with the protected endpoints, you must provide an HTTP Bearer Token for authentication. "
            "\n\n**Getting Started with API Tokens:**\n"
            "- Log in to the Qubiva portal.\n"
            "- Navigate to the left sidebar menu and select **API > API Tokens**.\n"
            "- Use the **Create New Token** form to generate a personal API token.\n"
            "- Include the generated token as a Bearer Token in the Authorization header of your HTTP requests."
        ),
    )

    # Define the path patterns you want to include
    included_patterns = [
        "/api/v1/projects",
        "/api/v1/add-users",
        "/api/v1/users",
        "/api/v1/org",
        "/api/v1/stats",
    ]

    # Filter paths that match any of the included patterns
    filtered_paths = {
        path: path_item
        for path, path_item in openapi_schema["paths"].items()
        if any(path.startswith(pattern) for pattern in included_patterns)
    }

    # Update the schema with the filtered paths
    openapi_schema["paths"] = filtered_paths

    app.openapi_schema = openapi_schema
    return app.openapi_schema
