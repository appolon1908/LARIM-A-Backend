from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Input):
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128, repr=False)


class AddressInput(Input):
    label: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    market_code: str = "DO-SDQ"


class QuoteInput(Input):
    service_code: str
    address_id: UUID
    market_code: str = "DO-SDQ"
    currency: str = "DOP"
    scheduled_start: AwareDatetime
    promotion_code: str | None = None
    add_ons: list[str] = Field(default_factory=list, max_length=0)


class BookingInput(Input):
    quote_id: UUID


class AuthorizeInput(Input):
    booking_id: UUID
    payment_method_token: str = Field(min_length=1, max_length=255, repr=False)


class AcceptInput(Input):
    booking_version: int = Field(ge=1)


class ProviderInput(Input):
    market_code: str = "DO-SDQ"
    services: list[str] = Field(min_length=1, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=30)


class StatusInput(Input):
    status: str = Field(
        pattern="^(DRAFT|SUBMITTED|UNDER_REVIEW|ACTION_REQUIRED|APPROVED|SUSPENDED|REJECTED)$"
    )
    reason: str = Field(min_length=3, max_length=500)


class OnlineInput(Input):
    online: bool


class LocationInput(Input):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AvailabilityInput(Input):
    start: AwareDatetime
    end: AwareDatetime


class ReviewInput(Input):
    booking_id: UUID
    rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=2000)


class RefundInput(Input):
    payment_id: UUID
    amount_minor: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)


class CaseInput(Input):
    booking_id: UUID | None = None
    body: str = Field(min_length=3, max_length=4000)


class ResolutionInput(Input):
    resolution: str = Field(min_length=3, max_length=4000)


class PayoutInput(Input):
    provider_id: UUID
    currency: str = Field(pattern="^(DOP|USD)$")


class MessageInput(Input):
    body: str = Field(min_length=1, max_length=4000)


class ConversationInput(Input):
    booking_id: UUID


class DocumentInput(Input):
    filename: str = Field(min_length=1, max_length=120)
    content_type: str = Field(pattern="^(image/jpeg|image/png|application/pdf)$")
    content_base64: str = Field(min_length=1, max_length=700000, repr=False)
    booking_id: UUID | None = None


class PromotionInput(Input):
    code: str = Field(min_length=3, max_length=80)
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern="^(DOP|USD)$")
    expires_at: AwareDatetime


class PricingInput(Input):
    base_minor: int = Field(gt=0)
    travel_minor: int = Field(ge=0)
    tax_bps: int = Field(ge=0, le=10000)
    fee_bps: int = Field(ge=0, le=10000)


class ServiceInput(Input):
    code: str = Field(min_length=3, max_length=80, pattern="^[A-Z0-9_]+$")
    category: str = Field(min_length=1, max_length=80)
    name: dict[str, str]
    market_code: str = "DO-SDQ"
    currency: str = Field(pattern="^(DOP|USD)$")
    duration_minutes: int = Field(gt=0, le=480)
    base_minor: int = Field(gt=0)
    required_skills: list[str] = Field(default_factory=list, max_length=30)


class RefreshInput(Input):
    refresh_token: str = Field(min_length=32, max_length=255, repr=False)


class RoleUpdate(Input):
    roles: list[str] = Field(min_length=1, max_length=12)
    reason: str = Field(min_length=5, max_length=500)


class BlockInput(Input):
    provider_id: UUID


class ProviderServices(Input):
    services: list[str] = Field(min_length=1, max_length=20)


class MoneyOutput(BaseModel):
    amountMinor: int
    currency: str


class BookingOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: UUID
    quote_id: UUID
    customer_id: UUID
    provider_id: UUID | None
    status: str
    version: int
    snapshot: dict
    address: dict
    scheduled_start: datetime
    scheduled_end: datetime
    created_at: datetime
    bookingNumber: str
    scheduledStart: datetime
    total: MoneyOutput


class QuoteOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: UUID
    expires_at: datetime
    total_minor: int
    currency: str
    pricing_policy_version: int
    provider_earning_minor: int
    snapshot: dict
