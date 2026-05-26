# Route modules for Qubiva
#
# Each module defines an APIRouter that is included by app.app.
# Import order here matches the include_router() order in app.py.

from app.routes import (
    health,
    internal,
    stats,
    auth_routes,
    org,
    projects,
    github,
    cloud_accounts,
    workspaces,
    requests,
    discovery,
    tasks,
    alerts,
    sso,
    analyst,
    dashboard,
    project_tokens,
    run_actions,
)

__all__ = [
    "health",
    "internal",
    "stats",
    "auth_routes",
    "org",
    "projects",
    "github",
    "cloud_accounts",
    "workspaces",
    "requests",
    "discovery",
    "tasks",
    "alerts",
    "sso",
    "analyst",
    "dashboard",
    "project_tokens",
    "run_actions",
]
