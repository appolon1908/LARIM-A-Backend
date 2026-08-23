from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from larimia.shared.db import get_db

router = APIRouter()

@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}
