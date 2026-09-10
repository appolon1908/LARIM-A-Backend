import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.finance.models import (
    PayoutAccount,
    PayoutBatch,
    PayoutItem,
    ProviderPayable,
)
from larimia.marketplace.models import (
    Assignment,
    AvailabilityException,
    AvailabilityRule,
    Provider,
    ProviderService,
    Service,
)
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.authorization import provider_for_principal, require_market
from larimia.shared.capabilities import (
    Capability,
    ensure_capability,
    require_capability,
)
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.PROVIDER_SELF_SERVICE))],
)


class Application(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    market_code: str = Field(min_length=1, max_length=16)
    requested_services: list[str] = Field(min_length=1, max_length=25)


class Availability(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, le=1_439)
    end_minute: int = Field(ge=1, le=1_440)
    timezone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_window(self):
        if self.end_minute <= self.start_minute:
            raise ValueError("end_minute must be greater than start_minute")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return self


class AvailabilityExceptionCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    exception_type: str = Field(pattern=r"^(UNAVAILABLE|AVAILABLE_OVERRIDE)$")

    @model_validator(mode="after")
    def validate_window(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("availability exception must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class PayoutAccountCreate(BaseModel):
    provider_code: str = Field(min_length=1, max_length=48)
    external_account_reference: str = Field(min_length=4, max_length=255)
    account_type: str = Field(pattern=r"^(BANK|WALLET|PLATFORM_ACCOUNT)$")
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    last4: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{4}$")


class ProviderStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(ACTIVE|SUSPENDED|REJECTED)$")
    onboarding_status: str | None = Field(default=None, min_length=1, max_length=48)
    reason: str = Field(min_length=5, max_length=1_000)


class ProviderServiceStatus(BaseModel):
    status: str = Field(pattern=r"^(APPROVED|REJECTED|SUSPENDED)$")
    reason: str = Field(min_length=5, max_length=1_000)


class PayoutAccountReview(BaseModel):
    status: str = Field(pattern=r"^(VERIFIED|RESTRICTED|DISABLED)$")
    active: bool
    reason: str = Field(min_length=5, max_length=1_000)


@router.post("/applications", status_code=201)
def apply(
    payload: Application,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    require_market(principal, payload.market_code)
    requested_codes = sorted(set(payload.requested_services))
    services = list(
        db.scalars(
            select(Service).where(
                Service.code.in_(requested_codes),
                Service.active.is_(True),
            )
        )
    )
    found_codes = {service.code for service in services}
    missing = sorted(set(requested_codes) - found_codes)
    if missing:
        raise HTTPException(
            422,
            detail={"code": "SERVICE_CODES_INVALID", "services": missing},
        )

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.apply",
        key=key,
        payload={**payload.model_dump(), "requested_services": requested_codes},
    )
    if replay is not None:
        return replay

    provider = db.scalar(
        select(Provider)
        .where(
            Provider.identity_issuer == principal.issuer,
            Provider.identity_subject == principal.subject,
        )
        .with_for_update()
    )
    if provider is None:
        provider = Provider(
            identity_issuer=principal.issuer,
            identity_subject=principal.subject,
            market_code=payload.market_code,
            status="APPLICANT",
            onboarding_status="APPLICATION_SUBMITTED",
            display_name=payload.display_name,
            version=1,
            created_at=datetime.now(UTC),
        )
        db.add(provider)
        db.flush()
        for service in services:
            db.add(
                ProviderService(
                    provider_id=provider.id,
                    service_id=service.id,
                    status="PENDING",
                )
            )
    else:
        if provider.market_code != payload.market_code:
            raise HTTPException(
                409, detail={"code": "PROVIDER_MARKET_IMMUTABLE"}
            )
        if provider.status not in {"APPLICANT", "REJECTED"}:
            raise HTTPException(
                409, detail={"code": "PROVIDER_ALREADY_EXISTS"}
            )
        provider.status = "APPLICANT"
        provider.onboarding_status = "APPLICATION_RESUBMITTED"
        provider.display_name = payload.display_name
        provider.version += 1
        existing_services = {
            row.service_id: row
            for row in db.scalars(
                select(ProviderService).where(
                    ProviderService.provider_id == provider.id
                )
            )
        }
        for service in services:
            row = existing_services.get(service.id)
            if row is None:
                db.add(
                    ProviderService(
                        provider_id=provider.id,
                        service_id=service.id,
                        status="PENDING",
                    )
                )
            elif row.status == "REJECTED":
                row.status = "PENDING"

    result = {
        "id": str(provider.id),
        "status": provider.status,
        "onboarding_status": provider.onboarding_status,
        "version": provider.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/application-status")
def application_status(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    provider = db.scalar(
        select(Provider).where(
            Provider.identity_issuer == principal.issuer,
            Provider.identity_subject == principal.subject,
        )
    )
    if provider is None:
        raise HTTPException(
            404, detail={"code": "APPLICATION_NOT_FOUND"}
        )
    return {
        "id": str(provider.id),
        "status": provider.status,
        "onboarding_status": provider.onboarding_status,
        "market_code": provider.market_code,
        "version": provider.version,
    }


@router.get("/me")
def me(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    return {
        "id": str(provider.id),
        "display_name": provider.display_name,
        "status": provider.status,
        "onboarding_status": provider.onboarding_status,
        "market_code": provider.market_code,
        "version": provider.version,
    }


@router.get("/me/availability")
def get_availability(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    rules = list(
        db.scalars(
            select(AvailabilityRule)
            .where(
                AvailabilityRule.provider_id == provider.id,
                AvailabilityRule.active.is_(True),
            )
            .order_by(
                AvailabilityRule.weekday,
                AvailabilityRule.start_minute,
            )
        )
    )
    exceptions = list(
        db.scalars(
            select(AvailabilityException)
            .where(AvailabilityException.provider_id == provider.id)
            .order_by(AvailabilityException.starts_at.desc())
            .limit(200)
        )
    )
    return {
        "rules": [
            {
                "id": str(row.id),
                "weekday": row.weekday,
                "start_minute": row.start_minute,
                "end_minute": row.end_minute,
                "timezone": row.timezone,
            }
            for row in rules
        ],
        "exceptions": [
            {
                "id": str(row.id),
                "starts_at": row.starts_at.isoformat(),
                "ends_at": row.ends_at.isoformat(),
                "exception_type": row.exception_type,
            }
            for row in exceptions
        ],
    }


@router.put("/me/availability")
def update_availability(
    rules: list[Availability],
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    if len(rules) > 50:
        raise HTTPException(
            422, detail={"code": "TOO_MANY_AVAILABILITY_RULES"}
        )

    provider = provider_for_principal(db, principal)
    if provider.status != "ACTIVE":
        raise HTTPException(
            409, detail={"code": "PROVIDER_NOT_ACTIVE"}
        )

    payload = [rule.model_dump() for rule in rules]
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.availability",
        key=key,
        payload=payload,
    )
    if replay is not None:
        return replay

    db.execute(
        delete(AvailabilityRule).where(
            AvailabilityRule.provider_id == provider.id
        )
    )
    for rule in rules:
        db.add(
            AvailabilityRule(
                provider_id=provider.id,
                active=True,
                **rule.model_dump(),
            )
        )

    result = {"updated": True, "count": len(rules)}
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/me/availability-exceptions", status_code=201)
def create_availability_exception(
    payload: AvailabilityExceptionCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.availability_exception.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    row = AvailabilityException(
        provider_id=provider.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    result = {
        "id": str(row.id),
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat(),
        "exception_type": row.exception_type,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/me/jobs")
def provider_jobs(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    rows = list(
        db.execute(
            select(Assignment, Booking)
            .join(Booking, Booking.id == Assignment.booking_id)
            .where(Assignment.provider_id == provider.id)
            .order_by(Booking.scheduled_start.desc())
            .limit(200)
        )
    )
    return {
        "items": [
            {
                "assignment_id": str(assignment.id),
                "booking_id": str(booking.id),
                "booking_number": booking.booking_number,
                "status": booking.status.value,
                "assignment_status": assignment.status,
                "market_code": booking.market_code,
                "scheduled_start": booking.scheduled_start.isoformat(),
                "scheduled_end": booking.scheduled_end.isoformat(),
                "version": booking.version,
            }
            for assignment, booking in rows
        ]
    }


@router.get("/me/earnings")
def provider_earnings(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    rows = list(
        db.execute(
            select(
                ProviderPayable.currency,
                ProviderPayable.status,
                func.coalesce(
                    func.sum(
                        ProviderPayable.net_minor
                        + ProviderPayable.adjustment_minor
                    ),
                    0,
                ),
                func.count(ProviderPayable.id),
            )
            .where(ProviderPayable.provider_id == provider.id)
            .group_by(
                ProviderPayable.currency,
                ProviderPayable.status,
            )
            .order_by(
                ProviderPayable.currency,
                ProviderPayable.status,
            )
        )
    )
    return {
        "provider_id": str(provider.id),
        "balances": [
            {
                "currency": currency,
                "status": status,
                "amount_minor": int(amount),
                "item_count": int(count),
            }
            for currency, status, amount, count in rows
        ],
    }


@router.get("/me/payouts")
def provider_payouts(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    rows = list(
        db.execute(
            select(PayoutItem, PayoutBatch)
            .join(PayoutBatch, PayoutBatch.id == PayoutItem.batch_id)
            .where(PayoutItem.provider_id == provider.id)
            .order_by(PayoutItem.created_at.desc())
            .limit(200)
        )
    )
    return {
        "items": [
            {
                "id": str(item.id),
                "batch_number": batch.batch_number,
                "status": item.status,
                "amount_minor": item.amount_minor,
                "currency": item.currency,
                "created_at": item.created_at.isoformat(),
            }
            for item, batch in rows
        ]
    }


@router.get("/me/payout-accounts")
def payout_accounts(
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    provider = provider_for_principal(db, principal)
    rows = list(
        db.scalars(
            select(PayoutAccount)
            .where(PayoutAccount.provider_id == provider.id)
            .order_by(PayoutAccount.created_at.desc())
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "provider_code": row.provider_code,
                "account_type": row.account_type,
                "country_code": row.country_code,
                "currency": row.currency,
                "last4": row.last4,
                "status": row.status,
                "active": row.active,
            }
            for row in rows
        ]
    }


@router.post("/me/payout-accounts", status_code=201)
def create_payout_account(
    payload: PayoutAccountCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    ensure_capability(Capability.PAYOUTS)
    provider = provider_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.payout_account.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    existing = db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.provider_id == provider.id,
            PayoutAccount.provider_code == payload.provider_code,
            PayoutAccount.external_account_reference
            == payload.external_account_reference,
        )
    )
    if existing is not None:
        raise HTTPException(
            409, detail={"code": "PAYOUT_ACCOUNT_ALREADY_EXISTS"}
        )
    now = datetime.now(UTC)
    row = PayoutAccount(
        provider_id=provider.id,
        provider_code=payload.provider_code,
        external_account_reference=payload.external_account_reference,
        account_type=payload.account_type,
        country_code=payload.country_code,
        currency=payload.currency,
        last4=payload.last4,
        status="PENDING_VERIFICATION",
        active=False,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        aggregate_type="payout_account",
        aggregate_id=str(row.id),
        event_type="payout.account_verification_requested.v1",
        payload={
            "payout_account_id": str(row.id),
            "provider_id": str(provider.id),
            "provider_code": row.provider_code,
        },
    )
    result = {
        "id": str(row.id),
        "status": row.status,
        "active": row.active,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/ops")
def ops_providers(
    principal: Principal = Depends(
        require_roles(
            Role.DISPATCHER,
            Role.QUALITY,
            Role.COMPLIANCE,
            Role.PLATFORM_ADMIN,
        )
    ),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(Provider)
            .order_by(Provider.created_at.desc())
            .limit(500)
        )
    )
    if principal.market_codes and Role.PLATFORM_ADMIN not in principal.roles:
        rows = [
            row for row in rows if row.market_code in principal.market_codes
        ]
    items = []
    for row in rows:
        services = list(
            db.execute(
                select(Service.code, ProviderService.status)
                .join(
                    ProviderService,
                    ProviderService.service_id == Service.id,
                )
                .where(ProviderService.provider_id == row.id)
                .order_by(Service.code)
            )
        )
        items.append(
            {
                "id": str(row.id),
                "display_name": row.display_name,
                "status": row.status,
                "onboarding_status": row.onboarding_status,
                "market_code": row.market_code,
                "version": row.version,
                "services": [
                    {"code": code, "status": status}
                    for code, status in services
                ],
            }
        )
    return {"items": items}


@router.patch("/{provider_id}/services/{service_id}")
def update_provider_service_status(
    provider_id: uuid.UUID,
    service_id: uuid.UUID,
    payload: ProviderServiceStatus,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(
        require_roles(Role.QUALITY, Role.COMPLIANCE, Role.PLATFORM_ADMIN)
    ),
    db: Session = Depends(get_db),
):
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(
            404, detail={"code": "PROVIDER_NOT_FOUND"}
        )
    require_market(principal, provider.market_code)
    row = db.scalar(
        select(ProviderService)
        .where(
            ProviderService.provider_id == provider.id,
            ProviderService.service_id == service_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(
            404, detail={"code": "PROVIDER_SERVICE_NOT_FOUND"}
        )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.service.review",
        key=key,
        payload={
            "provider_id": str(provider.id),
            "service_id": str(service_id),
            **payload.model_dump(),
        },
    )
    if replay is not None:
        return replay
    row.status = payload.status
    provider.version += 1
    provider.onboarding_status = (
        "SERVICE_APPROVED"
        if payload.status == "APPROVED"
        else "SERVICE_REVIEW_REQUIRED"
    )
    emit(
        db,
        aggregate_type="provider",
        aggregate_id=str(provider.id),
        event_type="provider.service_status_changed.v1",
        payload={
            "provider_id": str(provider.id),
            "service_id": str(service_id),
            "status": row.status,
            "reason": payload.reason,
        },
    )
    result = {
        "provider_id": str(provider.id),
        "service_id": str(service_id),
        "status": row.status,
        "provider_version": provider.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.patch("/{provider_id}/status")
def update_provider_status(
    provider_id: uuid.UUID,
    payload: ProviderStatusUpdate,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(
        require_roles(
            Role.QUALITY,
            Role.COMPLIANCE,
            Role.PLATFORM_ADMIN,
        )
    ),
    db: Session = Depends(get_db),
):
    provider = db.scalar(
        select(Provider)
        .where(Provider.id == provider_id)
        .with_for_update()
    )
    if provider is None:
        raise HTTPException(
            404, detail={"code": "PROVIDER_NOT_FOUND"}
        )
    require_market(principal, provider.market_code)
    if provider.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    allowed = {
        "APPLICANT": {"ACTIVE", "REJECTED"},
        "REJECTED": {"ACTIVE"},
        "ACTIVE": {"SUSPENDED", "REJECTED"},
        "SUSPENDED": {"ACTIVE", "REJECTED"},
    }
    if payload.status not in allowed.get(provider.status, set()):
        raise HTTPException(
            409, detail={"code": "INVALID_PROVIDER_STATUS_TRANSITION"}
        )
    if payload.status == "ACTIVE":
        approved = db.scalar(
            select(func.count())
            .select_from(ProviderService)
            .where(
                ProviderService.provider_id == provider.id,
                ProviderService.status == "APPROVED",
            )
        )
        if not approved:
            raise HTTPException(
                409, detail={"code": "APPROVED_SERVICE_REQUIRED"}
            )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.status.update",
        key=key,
        payload={
            "provider_id": str(provider.id),
            "version": if_match,
            **payload.model_dump(),
        },
    )
    if replay is not None:
        return replay
    previous = provider.status
    provider.status = payload.status
    provider.onboarding_status = (
        payload.onboarding_status
        or (
            "READY"
            if payload.status == "ACTIVE"
            else f"{payload.status}_BY_OPERATIONS"
        )
    )
    provider.version += 1
    emit(
        db,
        aggregate_type="provider",
        aggregate_id=str(provider.id),
        event_type="provider.status_changed.v1",
        payload={
            "provider_id": str(provider.id),
            "previous_status": previous,
            "status": provider.status,
            "reason": payload.reason,
            "version": provider.version,
        },
    )
    result = {
        "id": str(provider.id),
        "status": provider.status,
        "onboarding_status": provider.onboarding_status,
        "version": provider.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.patch("/ops/{provider_id}/payout-accounts/{account_id}")
def review_payout_account(
    provider_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: PayoutAccountReview,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(
        require_roles(Role.FINANCE, Role.PLATFORM_ADMIN)
    ),
    db: Session = Depends(get_db),
):
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(
            404, detail={"code": "PROVIDER_NOT_FOUND"}
        )
    require_market(principal, provider.market_code)
    account = db.scalar(
        select(PayoutAccount)
        .where(
            PayoutAccount.id == account_id,
            PayoutAccount.provider_id == provider.id,
        )
        .with_for_update()
    )
    if account is None:
        raise HTTPException(
            404, detail={"code": "PAYOUT_ACCOUNT_NOT_FOUND"}
        )
    if payload.active and payload.status != "VERIFIED":
        raise HTTPException(
            422, detail={"code": "ONLY_VERIFIED_ACCOUNT_CAN_BE_ACTIVE"}
        )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="provider.payout_account.review",
        key=key,
        payload={
            "provider_id": str(provider.id),
            "account_id": str(account.id),
            **payload.model_dump(),
        },
    )
    if replay is not None:
        return replay
    if payload.active:
        other_accounts = list(
            db.scalars(
                select(PayoutAccount)
                .where(
                    PayoutAccount.provider_id == provider.id,
                    PayoutAccount.provider_code == account.provider_code,
                    PayoutAccount.id != account.id,
                    PayoutAccount.active.is_(True),
                )
                .with_for_update()
            )
        )
        for other in other_accounts:
            other.active = False
            other.updated_at = datetime.now(UTC)
        db.flush()
    account.status = payload.status
    account.active = payload.active
    account.updated_at = datetime.now(UTC)
    emit(
        db,
        aggregate_type="payout_account",
        aggregate_id=str(account.id),
        event_type="payout.account_reviewed.v1",
        payload={
            "payout_account_id": str(account.id),
            "provider_id": str(provider.id),
            "status": account.status,
            "active": account.active,
            "reason": payload.reason,
        },
    )
    result = {
        "id": str(account.id),
        "status": account.status,
        "active": account.active,
    }
    complete(db, idem, result)
    db.commit()
    return result
