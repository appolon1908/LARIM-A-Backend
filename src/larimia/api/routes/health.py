import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.shared.db import get_db


router = APIRouter()


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    db.execute(text("SELECT 1"))
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
    finally:
        client.close()
    return {"status": "ready"}


@router.get("/version")
def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "version": settings.release_version,
        "git_sha": settings.git_sha,
        "image_digest": settings.image_digest,
        "migration_head": settings.migration_head,
        "environment": settings.env,
    }
