"""
Health check route for Qubiva.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health_check():
    """Health check endpoint for Kubernetes liveness/readiness probes."""
    return {"status": "healthy"}
