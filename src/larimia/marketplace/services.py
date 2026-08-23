import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from larimia.adapters.payment_registry import payment_provider
from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import (
    Assignment,
    AvailabilityException,
    AvailabilityRule,
    Customer,
    CustomerAddress,
    DispatchOffer,
    PaymentIntent,
    PricePolicy,
    Provider,
    ProviderService,
    Quote,
    Service,
    Visit,
)
from larimia.shared.audit import record_audit
from larimia.shared.errors import ConflictError, NotFoundError
from larimia.shared.events import emit


OFFER_TTL = timedelta(seconds=60)
QUOTE_TTL = timedelta(minutes=10)
SLOT_INCREMENT = timedelta(minutes=30)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ConflictError(
            "TIMEZONE_REQUIRED",
            f"{field_name} must include a timezone offset",
        )


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
        _require_aware(scheduled_start, "scheduled_start")
        if scheduled_start <= utcnow():
            raise ConflictError("INVALID_SCHEDULE", "scheduled_start must be in the future")
        if customer.market_code != market_code:
            raise ConflictError("MARKET_MISMATCH", "Customer is not active in this market")

        address = db.get(CustomerAddress, address_id)
        if address is None or address.customer_id != customer.id or not address.active:
            raise NotFoundError("ADDRESS_NOT_FOUND", "Address was not found")

        service = db.scalar(
            select(Service).where(
                Service.code == service_code,
                Service.active.is_(True),
            )
        )
        if service is None:
            raise NotFoundError("SERVICE_NOT_FOUND", "Service was not found")

        now = utcnow()
        policy = db.scalar(
            select(PricePolicy)
            .where(
                PricePolicy.market_code == market_code,
                PricePolicy.service_id == service.id,
                PricePolicy.active.is_(True),
                PricePolicy.effective_from <= now,
                or_(
                    PricePolicy.effective_until.is_(None),
                    PricePolicy.effective_until > now,
                ),
            )
            .order_by(PricePolicy.version.desc())
        )
        if policy is None:
            raise ConflictError("PRICE_UNAVAILABLE", "No active price policy")

        duration = timedelta(
            minutes=(
                service.duration_minutes
                + service.prep_minutes
                + service.cleanup_minutes
            )
        )
        scheduled_end = scheduled_start + duration
        subtotal = policy.base_price_minor + policy.travel_fee_minor
        tax = (subtotal * policy.tax_bps + 9_999) // 10_000

        quote = Quote(
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
            scheduled_end=scheduled_end,
            expires_at=now + QUOTE_TTL,
            status="ACTIVE",
            snapshot={
                "service": {
                    "id": str(service.id),
                    "code": service.code,
                    "name_es": service.name_es,
                    "name_en": service.name_en,
                    "duration_minutes": service.duration_minutes,
                    "prep_minutes": service.prep_minutes,
                    "cleanup_minutes": service.cleanup_minutes,
                },
                "price": {
                    "policy_id": str(policy.id),
                    "policy_version": policy.version,
                    "base_price_minor": policy.base_price_minor,
                    "travel_fee_minor": policy.travel_fee_minor,
                    "tax_bps": policy.tax_bps,
                    "currency": policy.currency,
                },
            },
            created_at=now,
        )
        db.add(quote)
        db.flush()
        emit(
            db,
            aggregate_type="quote",
            aggregate_id=str(quote.id),
            event_type="quote.created.v1",
            payload={
                "quote_id": str(quote.id),
                "customer_id": str(customer.id),
                "market_code": market_code,
                "total_minor": quote.total_minor,
                "currency": quote.currency,
            },
        )
        return quote


class AvailabilityService:
    @staticmethod
    def _covered_by_rule(
        rules: list[AvailabilityRule],
        provider_id: uuid.UUID,
        start: datetime,
        finish: datetime,
    ) -> bool:
        provider_rules = [rule for rule in rules if rule.provider_id == provider_id]
        for rule in provider_rules:
            try:
                timezone = ZoneInfo(rule.timezone)
            except ZoneInfoNotFoundError:
                continue

            local_start = start.astimezone(timezone)
            local_finish = finish.astimezone(timezone)
            if local_start.date() != local_finish.date():
                continue
            if local_start.weekday() != rule.weekday:
                continue

            start_minute = local_start.hour * 60 + local_start.minute
            finish_minute = local_finish.hour * 60 + local_finish.minute
            if rule.start_minute <= start_minute and rule.end_minute >= finish_minute:
                return True
        return False

    @staticmethod
    def slots(
        db: Session,
        *,
        service_code: str,
        market_code: str,
        from_time: datetime,
        days: int = 1,
    ) -> list[dict]:
        _require_aware(from_time, "from_time")
        service = db.scalar(
            select(Service).where(
                Service.code == service_code,
                Service.active.is_(True),
            )
        )
        if service is None:
            return []

        provider_ids = list(
            db.scalars(
                select(Provider.id)
                .join(
                    ProviderService,
                    ProviderService.provider_id == Provider.id,
                )
                .where(
                    Provider.market_code == market_code,
                    Provider.status == "ACTIVE",
                    ProviderService.service_id == service.id,
                    ProviderService.status == "APPROVED",
                )
                .order_by(Provider.id)
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
            minutes=(
                service.duration_minutes
                + service.prep_minutes
                + service.cleanup_minutes
            )
        )
        cursor = from_time.replace(second=0, microsecond=0)
        if cursor.minute % 30:
            cursor += timedelta(minutes=30 - cursor.minute % 30)

        output: list[dict] = []
        while cursor + duration <= end_window:
            finish = cursor + duration
            capacity = 0
            for provider_id in provider_ids:
                covered = AvailabilityService._covered_by_rule(
                    rules,
                    provider_id,
                    cursor,
                    finish,
                )
                blocked = any(
                    exception.provider_id == provider_id
                    and exception.starts_at < finish
                    and exception.ends_at > cursor
                    for exception in exceptions
                )
                busy = any(
                    assignment.provider_id == provider_id
                    and assignment.starts_at < finish
                    and assignment.ends_at > cursor
                    for assignment in assignments
                )
                if covered and not blocked and not busy:
                    capacity += 1

            if capacity:
                output.append(
                    {
                        "start": cursor.isoformat(),
                        "end": finish.isoformat(),
                        "provider_capacity": capacity,
                    }
                )
            cursor += SLOT_INCREMENT

        return output[:48]


class DispatchService:
    @staticmethod
    def create_offers(
        db: Session,
        *,
        booking: Booking,
        service_id: uuid.UUID,
        limit: int = 5,
    ) -> list[DispatchOffer]:
        provider_ids = list(
            db.scalars(
                select(Provider.id)
                .join(
                    ProviderService,
                    ProviderService.provider_id == Provider.id,
                )
                .where(
                    Provider.market_code == booking.market_code,
                    Provider.status == "ACTIVE",
                    ProviderService.service_id == service_id,
                    ProviderService.status == "APPROVED",
                )
                .order_by(Provider.id)
            )
        )
        if not provider_ids:
            return []

        busy = set(
            db.scalars(
                select(Assignment.provider_id).where(
                    Assignment.provider_id.in_(provider_ids),
                    Assignment.status.in_(["ACTIVE", "IN_SERVICE"]),
                    Assignment.starts_at < booking.scheduled_end,
                    Assignment.ends_at > booking.scheduled_start,
                )
            )
        )

        now = utcnow()
        candidates = [provider_id for provider_id in provider_ids if provider_id not in busy]
        offers: list[DispatchOffer] = []
        for rank, provider_id in enumerate(candidates[:limit], start=1):
            offer = db.scalar(
                select(DispatchOffer)
                .where(
                    DispatchOffer.booking_id == booking.id,
                    DispatchOffer.provider_id == provider_id,
                )
                .with_for_update()
            )
            if offer is None:
                offer = DispatchOffer(
                    booking_id=booking.id,
                    provider_id=provider_id,
                    created_at=now,
                )
                db.add(offer)

            offer.status = "OFFERED"
            offer.rank = rank
            offer.score = max(0.01, 1 - rank * 0.05)
            offer.expires_at = now + OFFER_TTL
            offer.accepted_at = None
            offers.append(offer)

        db.flush()
        for offer in offers:
            emit(
                db,
                aggregate_type="dispatch_offer",
                aggregate_id=str(offer.id),
                event_type="dispatch.offer_created.v1",
                payload={
                    "offer_id": str(offer.id),
                    "booking_id": str(booking.id),
                    "provider_id": str(offer.provider_id),
                    "expires_at": offer.expires_at.isoformat(),
                },
            )
        return offers

    @staticmethod
    def accept_offer(
        db: Session,
        *,
        offer_id: uuid.UUID,
        provider: Provider,
        expected_booking_version: int,
    ) -> Assignment:
        now = utcnow()
        offer = db.scalar(
            select(DispatchOffer)
            .where(DispatchOffer.id == offer_id)
            .with_for_update()
        )
        if offer is None or offer.provider_id != provider.id:
            raise NotFoundError("OFFER_NOT_FOUND", "Offer was not found")
        if offer.status != "OFFERED" or offer.expires_at <= now:
            raise ConflictError("OFFER_EXPIRED", "Offer is no longer available")

        booking = db.scalar(
            select(Booking)
            .where(Booking.id == offer.booking_id)
            .with_for_update()
        )
        if booking is None:
            raise NotFoundError("BOOKING_NOT_FOUND", "Booking was not found")
        if booking.version != expected_booking_version:
            raise ConflictError("VERSION_CONFLICT", "Booking version changed")
        if booking.status != BookingStatus.MATCHING:
            raise ConflictError(
                "BOOKING_NOT_MATCHING",
                "Booking is not accepting assignments",
            )

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
                "PROVIDER_UNAVAILABLE",
                "Provider already has an overlapping assignment",
            )

        assignment = Assignment(
            booking_id=booking.id,
            provider_id=provider.id,
            starts_at=booking.scheduled_start,
            ends_at=booking.scheduled_end,
            status="ACTIVE",
            created_at=now,
        )
        db.add(assignment)
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

        # A raw visit PIN is intentionally not placed in the shared outbox or
        # returned to the provider. A production customer-secret delivery
        # adapter is still required before visits can be activated.
        pin = f"{secrets.randbelow(1_000_000):06d}"
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
        return assignment


class VisitService:
    @staticmethod
    def transition(
        db: Session,
        *,
        booking: Booking,
        provider: Provider,
        action: str,
        pin: str | None = None,
    ) -> Visit:
        visit = db.scalar(
            select(Visit)
            .where(Visit.booking_id == booking.id)
            .with_for_update()
        )
        assignment = db.scalar(
            select(Assignment).where(Assignment.booking_id == booking.id)
        )
        if (
            visit is None
            or assignment is None
            or assignment.provider_id != provider.id
        ):
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
            supplied_hash = hashlib.sha256((pin or "").encode()).hexdigest()
            if not pin or not secrets.compare_digest(supplied_hash, visit.pin_hash):
                raise ConflictError("INVALID_PIN", "Arrival PIN is invalid")
            booking.status = BookingStatus.IN_SERVICE
            visit.status = "IN_SERVICE"
            visit.started_at = now
            assignment.status = "IN_SERVICE"
        elif action == "complete" and booking.status == BookingStatus.IN_SERVICE:
            booking.status = BookingStatus.COMPLETED
            visit.status = "COMPLETED"
            visit.completed_at = now
            assignment.status = "COMPLETED"
        else:
            raise ConflictError(
                "INVALID_VISIT_STATE",
                "Visit transition is not allowed",
            )

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
        db: Session,
        *,
        booking: Booking,
        customer: Customer,
        token: str,
        key: str,
    ) -> PaymentIntent:
        if booking.customer_total_minor <= 0:
            raise ConflictError("INVALID_PAYMENT_AMOUNT", "Booking amount must be positive")
        if len(booking.currency) != 3:
            raise ConflictError("INVALID_CURRENCY", "Booking currency is invalid")

        gateway = payment_provider()
        result = await gateway.authorize(
            token=token,
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            idempotency_key=key,
        )
        external_id = result.get("external_id")
        status = result.get("status")
        if not external_id or not status:
            raise ConflictError(
                "PAYMENT_PROVIDER_RESPONSE_INVALID",
                "Payment provider response was incomplete",
            )

        now = utcnow()
        intent = PaymentIntent(
            booking_id=booking.id,
            customer_id=customer.id,
            provider_code=gateway.code,
            external_id=external_id,
            status=status,
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            created_at=now,
            updated_at=now,
        )
        db.add(intent)
        db.flush()
        emit(
            db,
            aggregate_type="payment_intent",
            aggregate_id=str(intent.id),
            event_type="payment.authorized.v1",
            payload={
                "booking_id": str(booking.id),
                "payment_intent_id": str(intent.id),
                "provider_code": gateway.code,
            },
        )
        return intent
