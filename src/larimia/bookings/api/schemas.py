import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from larimia.bookings.domain.enums import BookingStatus


class BookingCreate(BaseModel):
    customer_id: uuid.UUID
    market_code: str = Field(min_length=3, max_length=16)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    scheduled_start: datetime
    scheduled_end: datetime
    customer_total_minor: int = Field(ge=0)


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    booking_number: str
    customer_id: uuid.UUID
    market_code: str
    status: BookingStatus
    currency: str
    customer_total_minor: int
    version: int
    scheduled_start: datetime
    scheduled_end: datetime
