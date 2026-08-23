from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from larimia.marketplace.models import (
    AvailabilityRule,
    Provider,
    ProviderService,
    Service,
)
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.authorization import provider_for_principal, require_market
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
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
            raise HTTPException(409, detail={"code": "PROVIDER_MARKET_IMMUTABLE"})
        if provider.status not in {"APPLICANT", "REJECTED"}:
            raise HTTPException(409, detail={"code": "PROVIDER_ALREADY_EXISTS"})

    result = {
        "id": str(provider.id),
        "status": provider.status,
        "onboarding_status": provider.onboarding_status,
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
        raise HTTPException(404, detail={"code": "APPLICATION_NOT_FOUND"})
    return {
        "id": str(provider.id),
        "status": provider.status,
        "onboarding_status": provider.onboarding_status,
        "market_code": provider.market_code,
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
        "market_code": provider.market_code,
        "version": provider.version,
    }


@router.put("/me/availability")
def update_availability(
    rules: list[Availability],
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    if len(rules) > 50:
        raise HTTPException(422, detail={"code": "TOO_MANY_AVAILABILITY_RULES"})

    provider = provider_for_principal(db, principal)
    if provider.status != "ACTIVE":
        raise HTTPException(409, detail={"code": "PROVIDER_NOT_ACTIVE"})

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
