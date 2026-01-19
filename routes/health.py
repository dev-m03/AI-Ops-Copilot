"""Health check route."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "ai-ops-copilot"}
