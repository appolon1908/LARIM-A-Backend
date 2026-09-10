import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import (
    Assignment,
    AvailabilityException,
    AvailabilityRule,
    BookingLine,
    Provider,
    ProviderService,
    Quote,
    Service,
)
from larimia.shared.db import Base
from larimia.shared.errors import ConflictError, NotFoundError
from larimia.shared.events import emit


SLOT_INCREMENT = timedelta(minutes=30)


class CapacityHold(Base):
    __tablename__ = "capacity_holds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=False,
    )
    market_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("services.id"),
        nullable=False,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_by_booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id"),
        unique=True,
    )
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


def _covered_by_rule(
    rules: list[AvailabilityRule],
    provider_id: uuid.UUID,
    start: datetime,
    finish: datetime,
) -> bool:
    for rule in rules:
        if rule.provider_id != provider_id:
            continue
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


class CapacityService:
    @staticmethod
    def _service(db: Session, service_code: str) -> Service | None:
        return db.scalar(
            select(Service).where(
                Service.code == service_code,
                Service.active.is_(True),
            )
        )

    @staticmethod
    def eligible_provider_ids(
        db: Session,
        *,
        market_code: str,
        service_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
    ) -> list[uuid.UUID]:
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
                    ProviderService.service_id == service_id,
                    ProviderService.status == "APPROVED",
                )
                .order_by(Provider.id)
            )
        )
        if not provider_ids:
            return []

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
                    AvailabilityException.starts_at < ends_at,
                    AvailabilityException.ends_at > starts_at,
                )
            )
        )
        assignments = list(
            db.scalars(
                select(Assignment).where(
                    Assignment.provider_id.in_(provider_ids),
                    Assignment.status.in_(["ACTIVE", "IN_SERVICE"]),
                    Assignment.starts_at < ends_at,
                    Assignment.ends_at > starts_at,
                )
            )
        )

        eligible: list[uuid.UUID] = []
        for provider_id in provider_ids:
            covered = _covered_by_rule(
                rules,
                provider_id,
                starts_at,
                ends_at,
            )
            blocked = any(
                exception.provider_id == provider_id
                and exception.starts_at < ends_at
                and exception.ends_at > starts_at
                for exception in exceptions
            )
            busy = any(
                assignment.provider_id == provider_id
                and assignment.starts_at < ends_at
                and assignment.ends_at > starts_at
                for assignment in assignments
            )
            if covered and not blocked and not busy:
                eligible.append(provider_id)
        return eligible

    @staticmethod
    def active_hold_quantity(
        db: Session,
        *,
        market_code: str,
        service_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
    ) -> int:
        now = utcnow()
        return int(
            db.scalar(
                select(func.coalesce(func.sum(CapacityHold.quantity), 0)).where(
                    CapacityHold.market_code == market_code,
                    CapacityHold.service_id == service_id,
                    CapacityHold.status == "ACTIVE",
                    CapacityHold.expires_at > now,
                    CapacityHold.starts_at < ends_at,
                    CapacityHold.ends_at > starts_at,
                )
            )
            or 0
        )

    @staticmethod
    def pending_booking_quantity(
        db: Session,
        *,
        market_code: str,
        service_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
    ) -> int:
        # Confirmed and matching bookings have consumed their quote hold but do
        # not yet have an assignment that would remove a provider from capacity.
        return int(
            db.scalar(
                select(func.count(Booking.id))
                .join(BookingLine, BookingLine.booking_id == Booking.id)
                .where(
                    Booking.market_code == market_code,
                    BookingLine.service_id == service_id,
                    Booking.status.in_(["CONFIRMED", "MATCHING"]),
                    Booking.scheduled_start < ends_at,
                    Booking.scheduled_end > starts_at,
                )
            )
            or 0
        )

    @staticmethod
    def available_capacity(
        db: Session,
        *,
        market_code: str,
        service_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
    ) -> int:
        provider_capacity = len(
            CapacityService.eligible_provider_ids(
                db,
                market_code=market_code,
                service_id=service_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )
        )
        held = CapacityService.active_hold_quantity(
            db,
            market_code=market_code,
            service_id=service_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        pending = CapacityService.pending_booking_quantity(
            db,
            market_code=market_code,
            service_id=service_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        return max(0, provider_capacity - held - pending)

    @staticmethod
    def slots(
        db: Session,
        *,
        service_code: str,
        market_code: str,
        from_time: datetime,
        days: int,
    ) -> list[dict]:
        if from_time.tzinfo is None or from_time.utcoffset() is None:
            raise ConflictError(
                "TIMEZONE_REQUIRED",
                "from_time must include a timezone offset",
            )
        service = CapacityService._service(db, service_code)
        if service is None:
            return []

        duration = timedelta(
            minutes=(
                service.duration_minutes
                + service.prep_minutes
                + service.cleanup_minutes
            )
        )
        end_window = from_time + timedelta(days=days)
        cursor = from_time.replace(second=0, microsecond=0)
        if cursor.minute % 30:
            cursor += timedelta(minutes=30 - cursor.minute % 30)

        output: list[dict] = []
        while cursor + duration <= end_window:
            finish = cursor + duration
            available = CapacityService.available_capacity(
                db,
                market_code=market_code,
                service_id=service.id,
                starts_at=cursor,
                ends_at=finish,
            )
            if available:
                output.append(
                    {
                        "start": cursor.isoformat(),
                        "end": finish.isoformat(),
                        "provider_capacity": available,
                    }
                )
            cursor += SLOT_INCREMENT
        return output[:96]

    @staticmethod
    def reserve_for_quote(db: Session, quote: Quote) -> CapacityHold:
        # Serialize reservations for the same service/window across API replicas.
        lock_key = (
            f"{quote.market_code}:{quote.service_id}:"
            f"{quote.scheduled_start.isoformat()}:{quote.scheduled_end.isoformat()}"
        )
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": lock_key},
        )

        existing = db.scalar(
            select(CapacityHold)
            .where(CapacityHold.quote_id == quote.id)
            .with_for_update()
        )
        if existing is not None:
            return existing

        available = CapacityService.available_capacity(
            db,
            market_code=quote.market_code,
            service_id=quote.service_id,
            starts_at=quote.scheduled_start,
            ends_at=quote.scheduled_end,
        )
        if available < 1:
            raise ConflictError(
                "CAPACITY_UNAVAILABLE",
                "The selected appointment time is no longer available",
            )

        hold = CapacityHold(
            quote_id=quote.id,
            customer_id=quote.customer_id,
            market_code=quote.market_code,
            service_id=quote.service_id,
            starts_at=quote.scheduled_start,
            ends_at=quote.scheduled_end,
            quantity=1,
            status="ACTIVE",
            expires_at=quote.expires_at,
            version=1,
            created_at=utcnow(),
        )
        db.add(hold)
        db.flush()
        emit(
            db,
            aggregate_type="capacity_hold",
            aggregate_id=str(hold.id),
            event_type="capacity.hold_created.v1",
            payload={
                "hold_id": str(hold.id),
                "quote_id": str(quote.id),
                "market_code": hold.market_code,
                "service_id": str(hold.service_id),
                "starts_at": hold.starts_at.isoformat(),
                "ends_at": hold.ends_at.isoformat(),
                "expires_at": hold.expires_at.isoformat(),
            },
        )
        return hold

    @staticmethod
    def active_hold_for_quote(
        db: Session,
        quote_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> CapacityHold:
        statement = select(CapacityHold).where(CapacityHold.quote_id == quote_id)
        if lock:
            statement = statement.with_for_update()
        hold = db.scalar(statement)
        if hold is None:
            raise NotFoundError(
                "CAPACITY_HOLD_NOT_FOUND",
                "Capacity hold was not found",
            )
        if hold.status != "ACTIVE" or hold.expires_at <= utcnow():
            raise ConflictError(
                "CAPACITY_HOLD_EXPIRED",
                "Capacity hold is no longer active",
            )
        return hold

    @staticmethod
    def consume(
        db: Session,
        *,
        hold: CapacityHold,
        booking: Booking,
    ) -> None:
        if hold.status != "ACTIVE" or hold.expires_at <= utcnow():
            raise ConflictError(
                "CAPACITY_HOLD_EXPIRED",
                "Capacity hold is no longer active",
            )
        if hold.customer_id != booking.customer_id:
            raise ConflictError(
                "CAPACITY_HOLD_CUSTOMER_MISMATCH",
                "Capacity hold does not belong to the booking customer",
            )
        if hold.starts_at != booking.scheduled_start or hold.ends_at != booking.scheduled_end:
            raise ConflictError(
                "CAPACITY_HOLD_WINDOW_MISMATCH",
                "Capacity hold does not match the booking schedule",
            )
        hold.status = "CONSUMED"
        hold.consumed_by_booking_id = booking.id
        hold.version += 1
        emit(
            db,
            aggregate_type="capacity_hold",
            aggregate_id=str(hold.id),
            event_type="capacity.hold_consumed.v1",
            payload={
                "hold_id": str(hold.id),
                "booking_id": str(booking.id),
                "version": hold.version,
            },
        )

    @staticmethod
    def release_for_booking(db: Session, booking: Booking) -> None:
        if booking.capacity_hold_id is None:
            return
        hold = db.get(CapacityHold, booking.capacity_hold_id, with_for_update=True)
        if hold is None or hold.status != "ACTIVE":
            return
        hold.status = "RELEASED"
        hold.version += 1
        emit(
            db,
            aggregate_type="capacity_hold",
            aggregate_id=str(hold.id),
            event_type="capacity.hold_released.v1",
            payload={
                "hold_id": str(hold.id),
                "booking_id": str(booking.id),
                "version": hold.version,
            },
        )
