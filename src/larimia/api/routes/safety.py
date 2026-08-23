import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.marketplace.models import SafetyIncident
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


class IncidentCreate(BaseModel):
    booking_id: uuid.UUID | None = None
    severity: str = Field(pattern=r"^S[1-4]$")
    category: str
    description: str


@router.post("/incidents", status_code=201)
def create(
    payload: IncidentCreate,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    idem, replay = reserve(
        db,
        actor_subject=p.subject,
        operation="safety.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    row = SafetyIncident(
        reporter_subject=p.subject,
        status="OPEN",
        created_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    result = {"id": str(row.id), "status": row.status, "severity": row.severity}
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/ops/incidents")
def ops(p: Principal = Depends(require_roles(Role.SAFETY)), db: Session = Depends(get_db)):
    rows = list(
        db.scalars(select(SafetyIncident).order_by(SafetyIncident.created_at.desc()).limit(200))
    )
    return {
        "items": [
            {
                "id": str(x.id),
                "severity": x.severity,
                "category": x.category,
                "status": x.status,
                "created_at": x.created_at.isoformat(),
            }
            for x in rows
        ]
    }
