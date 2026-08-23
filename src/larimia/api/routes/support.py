import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.marketplace.models import SupportCase
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


class CaseCreate(BaseModel):
    booking_id: uuid.UUID | None = None
    category: str
    subject: str
    message: str


@router.post("/cases", status_code=201)
def create(
    payload: CaseCreate,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    idem, replay = reserve(
        db,
        actor_subject=p.subject,
        operation="support.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    row = SupportCase(
        requester_subject=p.subject,
        status="OPEN",
        created_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    result = {"id": str(row.id), "status": row.status}
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/cases")
def mine(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(SupportCase)
            .where(SupportCase.requester_subject == p.subject)
            .order_by(SupportCase.created_at.desc())
        )
    )
    return {
        "items": [
            {"id": str(x.id), "subject": x.subject, "category": x.category, "status": x.status}
            for x in rows
        ]
    }


@router.get("/ops/cases")
def ops(p: Principal = Depends(require_roles(Role.SUPPORT)), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(SupportCase).order_by(SupportCase.created_at.desc()).limit(200)))
    return {
        "items": [
            {
                "id": str(x.id),
                "subject": x.subject,
                "category": x.category,
                "status": x.status,
                "requester": x.requester_subject,
            }
            for x in rows
        ]
    }
