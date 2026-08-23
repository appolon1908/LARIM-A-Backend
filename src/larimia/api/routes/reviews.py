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
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.REVIEWS))],
)


class ReviewCreate(BaseModel):
    booking_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


@router.post("", status_code=201)
def create_review(
    payload: ReviewCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    booking = db.get(Booking, payload.booking_id)
    if booking is None or booking.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    if booking.status.value not in {"COMPLETED", "SETTLING", "SETTLED"}:
        raise HTTPException(409, detail={"code": "REVIEW_NOT_ALLOWED"})

    assignment = db.scalar(
        select(Assignment).where(Assignment.booking_id == booking.id)
    )
    if assignment is None:
        raise HTTPException(409, detail={"code": "ASSIGNMENT_NOT_FOUND"})

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="review.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay

    existing = db.scalar(
        select(Review)
        .where(Review.booking_id == booking.id)
        .with_for_update()
    )
    if existing is not None:
        raise HTTPException(409, detail={"code": "REVIEW_ALREADY_EXISTS"})

    review = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=assignment.provider_id,
        rating=payload.rating,
        comment=payload.comment,
        status="PUBLISHED",
        created_at=datetime.now(UTC),
    )
    db.add(review)
    db.flush()

    result = {"id": str(review.id), "status": review.status}
    complete(db, idem, result)
    db.commit()
    return result
