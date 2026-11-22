from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Simple liveness check used by the frontend and for deployment."""
    return {"status": "ok", "service": settings.app_name, "version": settings.version}
