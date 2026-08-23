import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from larimia.bookings.domain.enums import BookingStatus
from larimia.shared.db import Base

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    market_code: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        default=BookingStatus.DRAFT,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3))
    customer_total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
