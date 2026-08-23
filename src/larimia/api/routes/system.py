from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.integrations.models import IntegrationStatus
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.capabilities import enabled_capabilities
from larimia.shared.db import get_db


router = APIRouter()


@router.get("/capabilities")
def capabilities():
    settings = get_settings()
    return {
        "environment": settings.env,
        "enabled": sorted(enabled_capabilities()),
    }


@router.get("/readiness")
def readiness(
    _: Principal = Depends(require_roles(Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    integrations = list(
        db.scalars(
            select(IntegrationStatus).order_by(
                IntegrationStatus.capability,
                IntegrationStatus.provider_code,
            )
        )
    )
    return {
        "environment": settings.env,
        "release": {
            "version": settings.release_version,
            "git_sha": settings.git_sha,
            "image_digest": settings.image_digest,
            "migration_head": settings.migration_head,
        },
        "capabilities": sorted(enabled_capabilities()),
        "integrations": [
            {
                "provider_code": item.provider_code,
                "capability": item.capability,
                "enabled": item.enabled,
                "readiness": item.readiness,
                "last_checked_at": (
                    item.last_checked_at.isoformat() if item.last_checked_at else None
                ),
                "has_error": bool(item.last_error),
            }
            for item in integrations
        ],
    }
