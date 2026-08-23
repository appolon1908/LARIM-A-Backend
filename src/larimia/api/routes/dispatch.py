import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import BookingLine, DispatchOffer
from larimia.marketplace.services import DispatchService
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.authorization import provider_for_principal, require_market
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.MATCHING))],
)


class AcceptOffer(BaseModel):
    booking_version: int = Field(ge=1)


def _offer_response(offer: DispatchOffer) -> dict:
    return {
        "id": str(offer.id),
        "booking_id": str(offer.booking_id),
        "provider_id": str(offer.provider_id),
        "rank": offer.rank,
        "score": float(offer.score),
        "expires_at": offer.expires_at.isoformat(),
        "status": offer.status,
    }


@router.post("/ops/bookings/{booking_id}/offers")
def create_offers(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.DISPATCHER)),
    db: Session = Depends(get_db),
):
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="dispatch.create_offers",
        key=key,
        payload={"booking_id": str(booking_id)},
    )
    if replay is not None:
        return replay

    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    require_market(principal, booking.market_code)
    if booking.status.value != "MATCHING":
        raise HTTPException(409, detail={"code": "BOOKING_NOT_MATCHING"})

    line = db.scalar(
        select(BookingLine)
        .where(BookingLine.booking_id == booking.id)
        .limit(1)
    )
    if line is None:
        raise HTTPException(409, detail={"code": "BOOKING_SERVICE_MISSING"})

    offers = DispatchService.create_offers(
        db,
        booking=booking,
        service_id=line.service_id,
    )
    result = {"items": [_offer_response(offer) for offer in offers]}
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/offers")
def list_provider_offers(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    rows = list(
        db.scalars(
            select(DispatchOffer)
            .where(
                DispatchOffer.provider_id == provider.id,
                DispatchOffer.status == "OFFERED",
            )
            .order_by(DispatchOffer.expires_at)
        )
    )
    return {"items": [_offer_response(row) for row in rows]}


@router.post("/offers/{offer_id}/accept")
def accept_offer(
    offer_id: uuid.UUID,
    payload: AcceptOffer,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="dispatch.accept_offer",
        key=key,
        payload={"offer_id": str(offer_id), **payload.model_dump()},
    )
    if replay is not None:
        return replay

    assignment = DispatchService.accept_offer(
        db,
        offer_id=offer_id,
        provider=provider,
        expected_booking_version=payload.booking_version,
    )
    result = {
        "assignment_id": str(assignment.id),
        "booking_id": str(assignment.booking_id),
        "status": assignment.status,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/offers/{offer_id}/decline")
def decline_offer(
    offer_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="dispatch.decline_offer",
        key=key,
        payload={"offer_id": str(offer_id)},
    )
    if replay is not None:
        return replay

    offer = db.scalar(
        select(DispatchOffer)
        .where(
            DispatchOffer.id == offer_id,
            DispatchOffer.provider_id == provider.id,
        )
        .with_for_update()
    )
    if offer is None:
        raise HTTPException(404, detail={"code": "OFFER_NOT_FOUND"})
    if offer.status != "OFFERED":
        raise HTTPException(409, detail={"code": "OFFER_NOT_ACTIVE"})

    offer.status = "DECLINED"
    result = {"offer_id": str(offer.id), "status": offer.status}
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/ops/board")
def dispatch_board(
    principal: Principal = Depends(require_roles(Role.DISPATCHER, Role.SUPPORT)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(Booking)
            .where(
                Booking.status.in_(
                    [
                        "CONFIRMED",
                        "MATCHING",
                        "ASSIGNED",
                        "EN_ROUTE",
                        "ARRIVED",
                        "IN_SERVICE",
                    ]
                )
            )
            .order_by(Booking.scheduled_start)
        )
    )
    if principal.market_codes and Role.PLATFORM_ADMIN not in principal.roles:
        rows = [row for row in rows if row.market_code in principal.market_codes]

    return {
        "items": [
            {
                "id": str(booking.id),
                "booking_number": booking.booking_number,
                "market_code": booking.market_code,
                "status": booking.status.value,
                "scheduled_start": booking.scheduled_start.isoformat(),
                "version": booking.version,
            }
            for booking in rows
        ]
    }
