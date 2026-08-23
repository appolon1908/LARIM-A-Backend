import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from larimia.adapters.payment_registry import payment_provider
from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import *
from larimia.shared.audit import record_audit
from larimia.shared.errors import ConflictError, NotFoundError
from larimia.shared.events import emit


def utcnow():
    return datetime.now(UTC)


class QuoteService:
    @staticmethod
    def create(
        db: Session,
        *,
        customer: Customer,
        address_id: uuid.UUID,
        service_code: str,
        market_code: str,
        scheduled_start: datetime,
    ) -> Quote:
        address = db.get(CustomerAddress, address_id)
        if not address or address.customer_id != customer.id or not address.active:
            raise NotFoundError("ADDRESS_NOT_FOUND", "Address was not found")
        service = db.scalar(
            select(Service).where(Service.code == service_code, Service.active.is_(True))
        )
        if not service:
            raise NotFoundError("SERVICE_NOT_FOUND", "Service was not found")
        policy = db.scalar(
            select(PricePolicy)
            .where(
                PricePolicy.market_code == market_code,
                PricePolicy.service_id == service.id,
                PricePolicy.active.is_(True),
                PricePolicy.effective_from <= utcnow(),
                or_(PricePolicy.effective_until.is_(None), PricePolicy.effective_until > utcnow()),
            )
            .order_by(PricePolicy.version.desc())
        )
        if not policy:
            raise ConflictError("PRICE_UNAVAILABLE", "No active price policy")
        end = scheduled_start + timedelta(
            minutes=service.duration_minutes + service.prep_minutes + service.cleanup_minutes
        )
        subtotal = policy.base_price_minor + policy.travel_fee_minor
        tax = (subtotal * policy.tax_bps + 9999) // 10000
        q = Quote(
            customer_id=customer.id,
            market_code=market_code,
            address_id=address.id,
            service_id=service.id,
            price_policy_id=policy.id,
            price_policy_version=policy.version,
            currency=policy.currency,
            subtotal_minor=subtotal,
            tax_minor=tax,
            total_minor=subtotal + tax,
            scheduled_start=scheduled_start,
            scheduled_end=end,
            expires_at=utcnow() + timedelta(minutes=10),
            status="ACTIVE",
            snapshot={
                "service": {
                    "id": str(service.id),
                    "code": service.code,
                    "name_es": service.name_es,
                    "name_en": service.name_en,
                    "duration_minutes": service.duration_minutes,
                },
                "policy_version": policy.version,
            },
            created_at=utcnow(),
        )
        db.add(q)
        db.flush()
        emit(
            db,
            aggregate_type="quote",
            aggregate_id=str(q.id),
            event_type="quote.created.v1",
            payload={
                "quote_id": str(q.id),
                "customer_id": str(customer.id),
                "total_minor": q.total_minor,
            },
        )
        return q


class AvailabilityService:
    @staticmethod
    def slots(
        db: Session, *, service_code: str, market_code: str, from_time: datetime, days: int = 1
    ) -> list[dict]:
        service = db.scalar(
            select(Service).where(Service.code == service_code, Service.active.is_(True))
        )
        if not service:
            return []
        provider_ids = list(
            db.scalars(
                select(Provider.id)
                .join(ProviderService, ProviderService.provider_id == Provider.id)
                .where(
                    Provider.market_code == market_code,
                    Provider.status == "ACTIVE",
                    ProviderService.service_id == service.id,
                    ProviderService.status == "APPROVED",
                )
            )
        )
        if not provider_ids:
            return []
        end_window = from_time + timedelta(days=days)
        rules = list(
            db.scalars(
                select(AvailabilityRule).where(
                    AvailabilityRule.provider_id.in_(provider_ids),
                    AvailabilityRule.active.is_(True),
                )
            )
        )
        exceptions = list(
            db.scalars(
                select(AvailabilityException).where(
                    AvailabilityException.provider_id.in_(provider_ids),
                    AvailabilityException.starts_at < end_window,
                    AvailabilityException.ends_at > from_time,
                )
            )
        )
        assignments = list(
            db.scalars(
                select(Assignment).where(
                    Assignment.provider_id.in_(provider_ids),
                    Assignment.status.in_(["ACTIVE", "IN_SERVICE"]),
                    Assignment.starts_at < end_window,
                    Assignment.ends_at > from_time,
                )
            )
        )
        duration = timedelta(
            minutes=service.duration_minutes + service.prep_minutes + service.cleanup_minutes
        )
        cursor = from_time.replace(second=0, microsecond=0)
        if cursor.minute % 30:
            cursor += timedelta(minutes=30 - cursor.minute % 30)
        slots = []
        while cursor + duration <= end_window:
            finish = cursor + duration
            cap = 0
            for pid in provider_ids:
                md = cursor.hour * 60 + cursor.minute
                emd = finish.hour * 60 + finish.minute
                ok = any(
                    r.provider_id == pid
                    and r.weekday == cursor.weekday()
                    and r.start_minute <= md
                    and r.end_minute >= emd
                    for r in rules
                )
                blocked = any(
                    e.provider_id == pid and e.starts_at < finish and e.ends_at > cursor
                    for e in exceptions
                )
                busy = any(
                    a.provider_id == pid and a.starts_at < finish and a.ends_at > cursor
                    for a in assignments
                )
                if ok and not blocked and not busy:
                    cap += 1
            if cap:
                slots.append(
                    {
                        "start": cursor.isoformat(),
                        "end": finish.isoformat(),
                        "provider_capacity": cap,
                    }
                )
            cursor += timedelta(minutes=30)
        return slots[:48]


class DispatchService:
    @staticmethod
    def create_offers(
        db: Session, *, booking: Booking, service_id: uuid.UUID, limit: int = 5
    ) -> list[DispatchOffer]:
        pids = list(
            db.scalars(
                select(Provider.id)
                .join(ProviderService, ProviderService.provider_id == Provider.id)
                .where(
                    Provider.market_code == booking.market_code,
                    Provider.status == "ACTIVE",
                    ProviderService.service_id == service_id,
                    ProviderService.status == "APPROVED",
                )
            )
        )
        busy = set(
            db.scalars(
                select(Assignment.provider_id).where(
                    Assignment.provider_id.in_(pids or [uuid.uuid4()]),
                    Assignment.status.in_(["ACTIVE", "IN_SERVICE"]),
                    Assignment.starts_at < booking.scheduled_end,
                    Assignment.ends_at > booking.scheduled_start,
                )
            )
        )
        now = utcnow()
        offers = []
        for rank, pid in enumerate([p for p in pids if p not in busy][:limit], 1):
            o = DispatchOffer(
                booking_id=booking.id,
                provider_id=pid,
                status="OFFERED",
                rank=rank,
                score=max(0.01, 1 - rank * 0.05),
                expires_at=now + timedelta(seconds=60),
                created_at=now,
            )
            db.add(o)
            offers.append(o)
        db.flush()
        for o in offers:
            emit(
                db,
                aggregate_type="dispatch_offer",
                aggregate_id=str(o.id),
                event_type="dispatch.offer_created.v1",
                payload={
                    "offer_id": str(o.id),
                    "booking_id": str(booking.id),
                    "provider_id": str(o.provider_id),
                },
            )
        return offers

    @staticmethod
    def accept_offer(
        db: Session, *, offer_id: uuid.UUID, provider: Provider, expected_booking_version: int
    ) -> Assignment:
        now = utcnow()
        offer = db.scalar(
            select(DispatchOffer).where(DispatchOffer.id == offer_id).with_for_update()
        )
        if not offer or offer.provider_id != provider.id:
            raise NotFoundError("OFFER_NOT_FOUND", "Offer was not found")
        if offer.status != "OFFERED" or offer.expires_at <= now:
            raise ConflictError("OFFER_EXPIRED", "Offer is no longer available")
        booking = db.scalar(select(Booking).where(Booking.id == offer.booking_id).with_for_update())
        if booking.version != expected_booking_version:
            raise ConflictError("VERSION_CONFLICT", "Booking version changed")
        if booking.status != BookingStatus.MATCHING:
            raise ConflictError("BOOKING_NOT_MATCHING", "Booking is not accepting assignments")
        overlap = db.scalar(
            select(Assignment.id)
            .where(
                Assignment.provider_id == provider.id,
                Assignment.status.in_(["ACTIVE", "IN_SERVICE"]),
                Assignment.starts_at < booking.scheduled_end,
                Assignment.ends_at > booking.scheduled_start,
            )
            .limit(1)
        )
        if overlap:
            raise ConflictError(
                "PROVIDER_UNAVAILABLE", "Provider already has an overlapping assignment"
            )
        a = Assignment(
            booking_id=booking.id,
            provider_id=provider.id,
            starts_at=booking.scheduled_start,
            ends_at=booking.scheduled_end,
            status="ACTIVE",
            created_at=now,
        )
        db.add(a)
        offer.status = "ACCEPTED"
        offer.accepted_at = now
        db.execute(
            update(DispatchOffer)
            .where(
                DispatchOffer.booking_id == booking.id,
                DispatchOffer.id != offer.id,
                DispatchOffer.status == "OFFERED",
            )
            .values(status="EXPIRED")
        )
        booking.status = BookingStatus.ASSIGNED
        booking.version += 1
        pin = f"{secrets.randbelow(1000000):06d}"
        db.add(
            Visit(
                booking_id=booking.id,
                provider_id=provider.id,
                status="ASSIGNED",
                pin_hash=hashlib.sha256(pin.encode()).hexdigest(),
            )
        )
        record_audit(
            db,
            actor=provider.identity_subject,
            action="dispatch.offer.accept",
            resource_type="booking",
            resource_id=str(booking.id),
            metadata={"provider_id": str(provider.id)},
        )
        emit(
            db,
            aggregate_type="booking",
            aggregate_id=str(booking.id),
            event_type="booking.assigned.v1",
            payload={
                "booking_id": str(booking.id),
                "provider_id": str(provider.id),
                "version": booking.version,
            },
        )
        db.flush()
        return a


class VisitService:
    @staticmethod
    def transition(
        db: Session, *, booking: Booking, provider: Provider, action: str, pin: str | None = None
    ) -> Visit:
        visit = db.scalar(select(Visit).where(Visit.booking_id == booking.id).with_for_update())
        assignment = db.scalar(select(Assignment).where(Assignment.booking_id == booking.id))
        if not visit or not assignment or assignment.provider_id != provider.id:
            raise NotFoundError("VISIT_NOT_FOUND", "Visit was not found")
        now = utcnow()
        if action == "en-route" and booking.status == BookingStatus.ASSIGNED:
            booking.status = BookingStatus.EN_ROUTE
            visit.status = "EN_ROUTE"
        elif action == "arrive" and booking.status == BookingStatus.EN_ROUTE:
            booking.status = BookingStatus.ARRIVED
            visit.status = "ARRIVED"
            visit.arrived_at = now
        elif action == "start" and booking.status == BookingStatus.ARRIVED:
            if not pin or hashlib.sha256(pin.encode()).hexdigest() != visit.pin_hash:
                raise ConflictError("INVALID_PIN", "Arrival PIN is invalid")
            booking.status = BookingStatus.IN_SERVICE
            visit.status = "IN_SERVICE"
            visit.started_at = now
        elif action == "complete" and booking.status == BookingStatus.IN_SERVICE:
            booking.status = BookingStatus.COMPLETED
            visit.status = "COMPLETED"
            visit.completed_at = now
            assignment.status = "COMPLETED"
        else:
            raise ConflictError("INVALID_VISIT_STATE", "Visit transition is not allowed")
        booking.version += 1
        record_audit(
            db,
            actor=provider.identity_subject,
            action=f"visit.{action}",
            resource_type="booking",
            resource_id=str(booking.id),
        )
        emit(
            db,
            aggregate_type="booking",
            aggregate_id=str(booking.id),
            event_type=f"booking.{action.replace('-', '_')}.v1",
            payload={
                "booking_id": str(booking.id),
                "status": booking.status.value,
                "version": booking.version,
            },
        )
        return visit


class PaymentService:
    @staticmethod
    async def authorize(
        db: Session, *, booking: Booking, customer: Customer, token: str, key: str
    ) -> PaymentIntent:
        gateway = payment_provider()
        result = await gateway.authorize(
            token=token,
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            idempotency_key=key,
        )
        pi = PaymentIntent(
            booking_id=booking.id,
            customer_id=customer.id,
            provider_code=gateway.code,
            external_id=result["external_id"],
            status=result["status"],
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(pi)
        emit(
            db,
            aggregate_type="payment_intent",
            aggregate_id=str(pi.id),
            event_type="payment.authorized.v1",
            payload={"booking_id": str(booking.id), "external_id": result["external_id"]},
        )
        return pi
