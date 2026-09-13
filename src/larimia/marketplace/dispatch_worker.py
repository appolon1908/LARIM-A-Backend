"""Resume expired offer batches after process restart, without Redis ownership state."""

from datetime import timedelta

from sqlalchemy import select

from larimia.config import get_settings
from larimia.shared.db import SessionLocal

from . import domain
from . import service as svc
from .models import DispatchSession, Offer, Payment, Provider, User, now
from .models import MarketplaceBooking as Booking


def recover() -> int:
    handled = 0
    with SessionLocal.begin() as db:
        sessions = db.scalars(
            select(DispatchSession).where(DispatchSession.status == "ACTIVE").limit(100)
        ).all()
        for initial in sessions:
            booking = db.scalar(
                select(Booking)
                .where(Booking.id == initial.booking_id)
                .with_for_update(skip_locked=True)
            )
            if not booking:
                continue
            session = db.scalar(
                select(DispatchSession).where(DispatchSession.id == initial.id).with_for_update()
            )
            if session is None or session.status != "ACTIVE":
                continue
            if booking.status != "OFFERED":
                session.status = "CLOSED"
                continue
            offers = db.scalars(select(Offer).where(Offer.booking_id == booking.id)).all()
            for offer in offers:
                if offer.status == "PENDING" and offer.expires_at <= now():
                    offer.status = "EXPIRED"
            if any(offer.status == "PENDING" for offer in offers):
                continue
            user = svc.get(db, User, booking.customer_id)
            excluded = {offer.provider_id for offer in offers}
            candidates = []
            if session.attempt < session.max_attempts:
                for provider in db.scalars(
                    select(Provider)
                    .where(Provider.status == "APPROVED", Provider.online.is_(True))
                    .limit(1000)
                ):
                    if provider.id not in excluded and svc.eligible(db, provider, booking):
                        distance = domain.distance_km(
                            provider.latitude,
                            provider.longitude,
                            booking.address["latitude"],
                            booking.address["longitude"],
                        )
                        candidates.append(
                            (
                                domain.score(
                                    distance,
                                    provider.rating,
                                    provider.completion_rate,
                                    provider.workload,
                                    get_settings().dispatch_weights,
                                ),
                                provider,
                            )
                        )
            candidates.sort(key=lambda row: (-row[0], str(row[1].id)))
            if candidates:
                session.attempt += 1
                for rank, provider in candidates[: get_settings().dispatch_batch_size]:
                    db.add(
                        Offer(
                            booking_id=booking.id,
                            provider_id=provider.id,
                            rank_score=rank,
                            attempt=session.attempt,
                            expires_at=now()
                            + timedelta(seconds=get_settings().dispatch_offer_seconds),
                        )
                    )
                svc.event(db, user, "DispatchOfferCreated", booking)
            else:
                svc.change(db, user, booking, "NO_PROVIDER_FOUND", "NoProviderFound")
                session.status = "EXHAUSTED"
                payment = db.scalar(
                    select(Payment).where(Payment.booking_id == booking.id).with_for_update()
                )
                if payment and payment.status == "AUTHORIZED":
                    from .payments import MockGateway

                    MockGateway().cancel(payment.external_reference)
                    payment.status = "CANCELLED"
            handled += 1
    return handled
