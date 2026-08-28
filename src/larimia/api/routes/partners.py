import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.commerce.models import (
    PartnerBookingRequest,
    PartnerInvoice,
    PartnerMembership,
    PartnerOrganization,
    PartnerProperty,
)
from larimia.marketplace.models import Service
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.authorization import require_market
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter(dependencies=[Depends(require_capability(Capability.PARTNERS))])


def _membership(db: Session, principal: Principal) -> PartnerMembership:
    row = db.scalar(
        select(PartnerMembership).where(
            PartnerMembership.identity_issuer == principal.issuer,
            PartnerMembership.identity_subject == principal.subject,
            PartnerMembership.active.is_(True),
        )
    )
    if row is None:
        raise HTTPException(403, detail={"code": "PARTNER_MEMBERSHIP_REQUIRED"})
    return row


def _organization(db: Session, principal: Principal) -> PartnerOrganization:
    membership = _membership(db, principal)
    row = db.get(PartnerOrganization, membership.organization_id)
    if row is None or row.status != "ACTIVE":
        raise HTTPException(403, detail={"code": "ACTIVE_PARTNER_REQUIRED"})
    return row


class PartnerBookingCreate(BaseModel):
    property_id: uuid.UUID
    guest_name: str = Field(min_length=1, max_length=160)
    guest_reference: str | None = Field(default=None, max_length=120)
    room_or_villa: str | None = Field(default=None, max_length=80)
    service_code: str = Field(min_length=1, max_length=80)
    scheduled_start: datetime
    notes: str | None = Field(default=None, max_length=2_000)


class PartnerBookingTransition(BaseModel):
    status: str = Field(pattern=r"^(QUOTED|CREDIT_APPROVED|BOOKED|REJECTED|CANCELLED)$")
    quote_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None
    approved_credit_minor: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=500)


@router.get("/me/organization")
def my_organization(
    principal: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
    db: Session = Depends(get_db),
):
    row = _organization(db, principal)
    return {
        "id": str(row.id),
        "code": row.code,
        "legal_name": row.legal_name,
        "market_code": row.market_code,
        "status": row.status,
        "billing_currency": row.billing_currency,
        "credit_limit_minor": row.credit_limit_minor,
        "outstanding_minor": row.outstanding_minor,
        "available_credit_minor": max(0, row.credit_limit_minor - row.outstanding_minor),
        "payment_terms_days": row.payment_terms_days,
        "version": row.version,
    }


@router.get("/me/properties")
def properties(
    principal: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
    db: Session = Depends(get_db),
):
    org = _organization(db, principal)
    rows = list(
        db.scalars(
            select(PartnerProperty)
            .where(
                PartnerProperty.organization_id == org.id,
                PartnerProperty.active.is_(True),
            )
            .order_by(PartnerProperty.name)
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "address_line_1": row.address_line_1,
                "city": row.city,
                "country_code": row.country_code,
            }
            for row in rows
        ]
    }


@router.post("/booking-requests", status_code=201)
def create_booking_request(
    payload: PartnerBookingCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
    db: Session = Depends(get_db),
):
    org = _organization(db, principal)
    require_market(principal, org.market_code)
    if payload.scheduled_start.tzinfo is None or payload.scheduled_start <= datetime.now(UTC):
        raise HTTPException(422, detail={"code": "INVALID_SCHEDULE"})
    prop = db.get(PartnerProperty, payload.property_id)
    if prop is None or prop.organization_id != org.id or not prop.active:
        raise HTTPException(404, detail={"code": "PARTNER_PROPERTY_NOT_FOUND"})
    service = db.scalar(
        select(Service).where(Service.code == payload.service_code, Service.active.is_(True))
    )
    if service is None:
        raise HTTPException(422, detail={"code": "SERVICE_CODE_INVALID"})

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="partner.booking_request.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay

    now = datetime.now(UTC)
    row = PartnerBookingRequest(
        organization_id=org.id,
        property_id=prop.id,
        requested_by_subject=principal.subject,
        guest_name=payload.guest_name,
        guest_reference=payload.guest_reference,
        room_or_villa=payload.room_or_villa,
        service_code=service.code,
        market_code=org.market_code,
        scheduled_start=payload.scheduled_start,
        notes=payload.notes,
        status="PENDING_QUOTE",
        quote_id=None,
        booking_id=None,
        approved_credit_minor=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        aggregate_type="partner_booking_request",
        aggregate_id=str(row.id),
        event_type="partner.booking_requested.v1",
        payload={
            "request_id": str(row.id),
            "organization_id": str(org.id),
            "market_code": org.market_code,
            "service_code": service.code,
        },
    )
    result = {"id": str(row.id), "status": row.status, "version": row.version}
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/booking-requests")
def list_booking_requests(
    principal: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
    db: Session = Depends(get_db),
):
    org = _organization(db, principal)
    rows = list(
        db.scalars(
            select(PartnerBookingRequest)
            .where(PartnerBookingRequest.organization_id == org.id)
            .order_by(PartnerBookingRequest.created_at.desc())
            .limit(200)
        )
    )
    return {"items": [_serialize_request(row) for row in rows]}


@router.get("/invoices")
def invoices(
    principal: Principal = Depends(require_roles(Role.PARTNER_BOOKER, Role.FINANCE)),
    db: Session = Depends(get_db),
):
    org = _organization(db, principal)
    rows = list(
        db.scalars(
            select(PartnerInvoice)
            .where(PartnerInvoice.organization_id == org.id)
            .order_by(PartnerInvoice.created_at.desc())
            .limit(200)
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "invoice_number": row.invoice_number,
                "status": row.status,
                "currency": row.currency,
                "total_minor": row.total_minor,
                "due_at": row.due_at.isoformat() if row.due_at else None,
                "issued_at": row.issued_at.isoformat() if row.issued_at else None,
            }
            for row in rows
        ]
    }


@router.get("/ops/booking-requests")
def ops_booking_requests(
    principal: Principal = Depends(require_roles(Role.DISPATCHER, Role.FINANCE, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    query = select(PartnerBookingRequest).order_by(PartnerBookingRequest.created_at.desc()).limit(500)
    rows = list(db.scalars(query))
    if principal.market_codes and Role.PLATFORM_ADMIN not in principal.roles:
        rows = [row for row in rows if row.market_code in principal.market_codes]
    return {"items": [_serialize_request(row) for row in rows]}


@router.post("/ops/booking-requests/{request_id}/transition")
def transition_booking_request(
    request_id: uuid.UUID,
    payload: PartnerBookingTransition,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.DISPATCHER, Role.FINANCE, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(PartnerBookingRequest)
        .where(PartnerBookingRequest.id == request_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, detail={"code": "PARTNER_BOOKING_REQUEST_NOT_FOUND"})
    require_market(principal, row.market_code)
    if row.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})

    allowed = {
        "PENDING_QUOTE": {"QUOTED", "REJECTED", "CANCELLED"},
        "QUOTED": {"CREDIT_APPROVED", "REJECTED", "CANCELLED"},
        "CREDIT_APPROVED": {"BOOKED", "REJECTED", "CANCELLED"},
        "BOOKED": {"CANCELLED"},
        "REJECTED": set(),
        "CANCELLED": set(),
    }
    if payload.status not in allowed.get(row.status, set()):
        raise HTTPException(409, detail={"code": "INVALID_PARTNER_BOOKING_TRANSITION"})
    if payload.status == "QUOTED" and payload.quote_id is None:
        raise HTTPException(422, detail={"code": "QUOTE_ID_REQUIRED"})
    if payload.status == "CREDIT_APPROVED":
        if Role.FINANCE not in principal.roles and Role.PLATFORM_ADMIN not in principal.roles:
            raise HTTPException(403, detail={"code": "FINANCE_APPROVAL_REQUIRED"})
        if payload.approved_credit_minor is None:
            raise HTTPException(422, detail={"code": "APPROVED_CREDIT_REQUIRED"})
        org = db.get(PartnerOrganization, row.organization_id)
        if org is None or org.outstanding_minor + payload.approved_credit_minor > org.credit_limit_minor:
            raise HTTPException(409, detail={"code": "PARTNER_CREDIT_LIMIT_EXCEEDED"})
    if payload.status == "BOOKED" and payload.booking_id is None:
        raise HTTPException(422, detail={"code": "BOOKING_ID_REQUIRED"})

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="partner.booking_request.transition",
        key=key,
        payload={"request_id": str(request_id), "version": if_match, **payload.model_dump()},
    )
    if replay is not None:
        return replay

    row.status = payload.status
    if payload.quote_id is not None:
        row.quote_id = payload.quote_id
    if payload.booking_id is not None:
        row.booking_id = payload.booking_id
    if payload.approved_credit_minor is not None:
        row.approved_credit_minor = payload.approved_credit_minor
    row.version += 1
    row.updated_at = datetime.now(UTC)
    emit(
        db,
        aggregate_type="partner_booking_request",
        aggregate_id=str(row.id),
        event_type="partner.booking_request_transitioned.v1",
        payload={
            "request_id": str(row.id),
            "status": row.status,
            "version": row.version,
            "actor": principal.subject,
            "reason": payload.reason,
        },
    )
    result = _serialize_request(row)
    complete(db, idem, result)
    db.commit()
    return result


def _serialize_request(row: PartnerBookingRequest) -> dict:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "property_id": str(row.property_id),
        "guest_name": row.guest_name,
        "guest_reference": row.guest_reference,
        "room_or_villa": row.room_or_villa,
        "service_code": row.service_code,
        "market_code": row.market_code,
        "scheduled_start": row.scheduled_start.isoformat(),
        "status": row.status,
        "quote_id": str(row.quote_id) if row.quote_id else None,
        "booking_id": str(row.booking_id) if row.booking_id else None,
        "approved_credit_minor": row.approved_credit_minor,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
    }


class PartnerOrganizationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z0-9][A-Z0-9_-]+$")
    legal_name: str = Field(min_length=2, max_length=200)
    market_code: str = Field(min_length=1, max_length=16)
    billing_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    credit_limit_minor: int = Field(default=0, ge=0)
    payment_terms_days: int = Field(default=0, ge=0, le=365)


class PartnerOrganizationUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=200)
    status: str | None = Field(default=None, pattern=r"^(PENDING_REVIEW|ACTIVE|SUSPENDED|CLOSED)$")
    credit_limit_minor: int | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)


class PartnerMemberCreate(BaseModel):
    identity_issuer: str = Field(min_length=1, max_length=255)
    identity_subject: str = Field(min_length=1, max_length=255)
    role_code: str = Field(default="BOOKER", pattern=r"^(BOOKER|ADMIN|FINANCE)$")


class PartnerPropertyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    name: str = Field(min_length=2, max_length=180)
    address_line_1: str = Field(min_length=2, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@router.get("/ops/organizations")
def ops_organizations(
    principal: Principal = Depends(require_roles(Role.FINANCE, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(PartnerOrganization)
            .order_by(PartnerOrganization.legal_name)
            .limit(500)
        )
    )
    if principal.market_codes and Role.PLATFORM_ADMIN not in principal.roles:
        rows = [row for row in rows if row.market_code in principal.market_codes]
    return {
        "items": [
            {
                "id": str(row.id),
                "code": row.code,
                "legal_name": row.legal_name,
                "market_code": row.market_code,
                "status": row.status,
                "billing_currency": row.billing_currency,
                "credit_limit_minor": row.credit_limit_minor,
                "outstanding_minor": row.outstanding_minor,
                "payment_terms_days": row.payment_terms_days,
                "version": row.version,
            }
            for row in rows
        ]
    }


@router.post("/ops/organizations", status_code=201)
def create_organization(
    payload: PartnerOrganizationCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    require_market(principal, payload.market_code)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="partner.organization.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    existing = db.scalar(
        select(PartnerOrganization).where(PartnerOrganization.code == payload.code)
    )
    if existing is not None:
        raise HTTPException(409, detail={"code": "PARTNER_CODE_EXISTS"})
    now = datetime.now(UTC)
    row = PartnerOrganization(
        code=payload.code,
        legal_name=payload.legal_name,
        market_code=payload.market_code,
        status="PENDING_REVIEW",
        billing_currency=payload.billing_currency,
        credit_limit_minor=payload.credit_limit_minor,
        outstanding_minor=0,
        payment_terms_days=payload.payment_terms_days,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        aggregate_type="partner_organization",
        aggregate_id=str(row.id),
        event_type="partner.organization_created.v1",
        payload={"organization_id": str(row.id), "market_code": row.market_code},
    )
    result = {"id": str(row.id), "status": row.status, "version": row.version}
    complete(db, idem, result)
    db.commit()
    return result


@router.patch("/ops/organizations/{organization_id}")
def update_organization(
    organization_id: uuid.UUID,
    payload: PartnerOrganizationUpdate,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.FINANCE, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(PartnerOrganization)
        .where(PartnerOrganization.id == organization_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, detail={"code": "PARTNER_ORGANIZATION_NOT_FOUND"})
    require_market(principal, row.market_code)
    if row.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    if payload.credit_limit_minor is not None and payload.credit_limit_minor < row.outstanding_minor:
        raise HTTPException(409, detail={"code": "CREDIT_LIMIT_BELOW_OUTSTANDING"})
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="partner.organization.update",
        key=key,
        payload={"organization_id": str(row.id), "version": if_match, **payload.model_dump()},
    )
    if replay is not None:
        return replay
    if payload.legal_name is not None:
        row.legal_name = payload.legal_name
    if payload.status is not None:
        row.status = payload.status
    if payload.credit_limit_minor is not None:
        row.credit_limit_minor = payload.credit_limit_minor
    if payload.payment_terms_days is not None:
        row.payment_terms_days = payload.payment_terms_days
    row.version += 1
    row.updated_at = datetime.now(UTC)
    emit(
        db,
        aggregate_type="partner_organization",
        aggregate_id=str(row.id),
        event_type="partner.organization_updated.v1",
        payload={"organization_id": str(row.id), "status": row.status, "version": row.version},
    )
    result = {"id": str(row.id), "status": row.status, "version": row.version}
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/ops/organizations/{organization_id}/members", status_code=201)
def add_partner_member(
    organization_id: uuid.UUID,
    payload: PartnerMemberCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    org = db.get(PartnerOrganization, organization_id)
    if org is None:
        raise HTTPException(404, detail={"code": "PARTNER_ORGANIZATION_NOT_FOUND"})
    require_market(principal, org.market_code)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="partner.member.create",
        key=key,
        payload={"organization_id": str(org.id), **payload.model_dump()},
    )
    if replay is not None:
        return replay
    existing = db.scalar(
        select(PartnerMembership).where(
            PartnerMembership.identity_issuer == payload.identity_issuer,
            PartnerMembership.identity_subject == payload.identity_subject,
        )
    )
    if existing is not None:
        raise HTTPException(409, detail={"code": "PARTNER_IDENTITY_EXISTS"})
    row = PartnerMembership(
        organization_id=org.id,
        identity_issuer=payload.identity_issuer,
        identity_subject=payload.identity_subject,
        role_code=payload.role_code,
        active=True,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    result = {"id": str(row.id), "organization_id": str(org.id), "role_code": row.role_code}
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/ops/organizations/{organization_id}/properties", status_code=201)
def add_partner_property(
    organization_id: uuid.UUID,
    payload: PartnerPropertyCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    org = db.get(PartnerOrganization, organization_id)
    if org is None:
        raise HTTPException(404, detail={"code": "PARTNER_ORGANIZATION_NOT_FOUND"})
    require_market(principal, org.market_code)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="partner.property.create",
        key=key,
        payload={"organization_id": str(org.id), **payload.model_dump()},
    )
    if replay is not None:
        return replay
    existing = db.scalar(
        select(PartnerProperty).where(
            PartnerProperty.organization_id == org.id,
            PartnerProperty.code == payload.code,
        )
    )
    if existing is not None:
        raise HTTPException(409, detail={"code": "PARTNER_PROPERTY_CODE_EXISTS"})
    row = PartnerProperty(
        organization_id=org.id,
        active=True,
        created_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    result = {"id": str(row.id), "organization_id": str(org.id), "code": row.code}
    complete(db, idem, result)
    db.commit()
    return result
