from datetime import UTC, datetime

from sqlalchemy import select

from larimia.marketplace.capacity import CapacityHold
from larimia.marketplace.models import DispatchOffer, Quote
from larimia.shared.db import SessionLocal
from larimia.shared.events import emit


def expire_marketplace_state(limit: int = 500) -> dict[str, int]:
    now = datetime.now(UTC)
    expired_holds = 0
    expired_offers = 0

    with SessionLocal() as db:
        holds = list(
            db.scalars(
                select(CapacityHold)
                .where(
                    CapacityHold.status == "ACTIVE",
                    CapacityHold.expires_at <= now,
                )
                .order_by(CapacityHold.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for hold in holds:
            hold.status = "EXPIRED"
            hold.version += 1
            quote = db.get(Quote, hold.quote_id, with_for_update=True)
            if quote is not None and quote.status == "ACTIVE":
                quote.status = "EXPIRED"
            emit(
                db,
                aggregate_type="capacity_hold",
                aggregate_id=str(hold.id),
                event_type="capacity.hold_expired.v1",
                payload={
                    "hold_id": str(hold.id),
                    "quote_id": str(hold.quote_id),
                    "version": hold.version,
                },
            )
            expired_holds += 1

        offers = list(
            db.scalars(
                select(DispatchOffer)
                .where(
                    DispatchOffer.status == "OFFERED",
                    DispatchOffer.expires_at <= now,
                )
                .order_by(DispatchOffer.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for offer in offers:
            offer.status = "EXPIRED"
            emit(
                db,
                aggregate_type="dispatch_offer",
                aggregate_id=str(offer.id),
                event_type="dispatch.offer_expired.v1",
                payload={
                    "offer_id": str(offer.id),
                    "booking_id": str(offer.booking_id),
                    "provider_id": str(offer.provider_id),
                },
            )
            expired_offers += 1
        db.commit()

    return {
        "expired_holds": expired_holds,
        "expired_offers": expired_offers,
    }
