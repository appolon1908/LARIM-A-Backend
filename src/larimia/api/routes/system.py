from fastapi import APIRouter
from larimia.config import get_settings
from larimia.shared.capabilities import enabled_capabilities

router = APIRouter()

@router.get("/capabilities")
def capabilities():
    settings = get_settings()
    return {
        "environment": settings.env,
        "auth_mode": settings.auth_mode,
        "enabled": sorted(enabled_capabilities()),
    }
