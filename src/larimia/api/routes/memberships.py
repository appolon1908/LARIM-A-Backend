from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.marketplace.models import Membership
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


class Subscribe(BaseModel):
    plan_code: str


@router.get("/plans")
def plans():
    return {
        "items": [
            {"code": "LARIMIA_PLUS", "monthly_credits": 1},
            {"code": "LARIMIA_PREMIER", "monthly_credits": 2},
        ]
    }


@router.post("/subscriptions", status_code=201)
def subscribe(
    payload: Subscribe,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    c = customer_for_principal(db, p)
    idem, replay = reserve(
        db,
        actor_subject=p.subject,
        operation="membership.subscribe",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    row = db.scalar(
        select(Membership).where(Membership.customer_id == c.id, Membership.status == "ACTIVE")
    )
    if not row:
        row = Membership(
            customer_id=c.id,
            plan_code=payload.plan_code,
            status="ACTIVE",
            started_at=datetime.now(UTC),
        )
        db.add(row)
        db.flush()
    result = {"id": str(row.id), "plan_code": row.plan_code, "status": row.status}
    complete(db, idem, result)
    db.commit()
    return result
