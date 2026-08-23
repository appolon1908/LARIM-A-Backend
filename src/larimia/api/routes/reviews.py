import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import Assignment, Review
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


class ReviewCreate(BaseModel):
    booking_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


@router.post("", status_code=201)
def create(
    payload: ReviewCreate,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    c = customer_for_principal(db, p)
    b = db.get(Booking, payload.booking_id)
    if not b or b.customer_id != c.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    if b.status.value not in {"COMPLETED", "SETTLING", "SETTLED"}:
        raise HTTPException(409, detail={"code": "REVIEW_NOT_ALLOWED"})
    a = db.scalar(select(Assignment).where(Assignment.booking_id == b.id))
    if not a:
        raise HTTPException(409, detail={"code": "ASSIGNMENT_NOT_FOUND"})
    idem, replay = reserve(
        db,
        actor_subject=p.subject,
        operation="review.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    row = Review(
        booking_id=b.id,
        customer_id=c.id,
        provider_id=a.provider_id,
        rating=payload.rating,
        comment=payload.comment,
        status="PUBLISHED",
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    result = {"id": str(row.id), "status": row.status}
    complete(db, idem, result)
    db.commit()
    return result
