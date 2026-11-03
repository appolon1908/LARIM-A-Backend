from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.shared.audit import AuditEvent, record_audit
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key

from . import schemas as s
from . import service as svc
from .commands import command
from .models import (
    Address,
    Case,
    Earning,
    Notification,
    Offer,
    Payment,
    Provider,
    Service,
    User,
    now,
)
from .models import MarketplaceBooking as Booking
from .security import current_user, password_hash, require, verify_password

router = APIRouter()


def run(db, user, operation, key, payload, action):
    return command(db, user.subject, operation, key, payload, action)


@router.post("/auth/register", status_code=201)
def register(
    payload: s.Credentials,
    key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    if get_settings().auth_mode != "local":
        raise HTTPException(403, "Registration is owned by the configured identity provider")
    email = payload.email.lower()

    def action():
        if db.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "Account already exists")
        user = User(
            subject=email,
            email=email,
            password_hash=password_hash(payload.password),
            roles=["customer"],
        )
        db.add(user)
        db.flush()
        emit(
            db,
            aggregate_type="user",
            aggregate_id=str(user.id),
            event_type="CustomerRegistered",
            payload={"user_id": str(user.id)},
        )
        return {"id": str(user.id), "email": user.email}

    # Password is never stored in an idempotency payload, only a one-way request digest.
    return command(db, "registration:" + email, "register", key, payload.model_dump(), action)


@router.post("/auth/login")
def login(payload: s.LoginInput, db: Session = Depends(get_db)):
    if get_settings().auth_mode != "local":
        raise HTTPException(403, "Login is owned by the identity provider")
    user = db.scalar(select(User).where(User.email == payload.email.lower(), User.active.is_(True)))
    if (
        not user
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(401, "Invalid credentials")
    record_audit(
        db,
        actor=user.subject,
        action="LoginSucceeded",
        resource_type="user",
        resource_id=str(user.id),
    )
    from .security import new_session

    session = new_session(db, user, payload.device_id)
    db.commit()
    return session


@router.get("/me")
def me(user: User = Depends(current_user)):
    return svc.serialize(user)


@router.post("/me/addresses", status_code=201)
def address(
    payload: s.AddressInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    def action():
        row = Address(customer_id=user.id, **payload.model_dump())
        db.add(row)
        db.flush()
        return svc.serialize(row)

    return run(db, user, "address.create", key, payload.model_dump(), action)


@router.get("/me/addresses")
def addresses(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(Address).where(Address.customer_id == user.id).limit(limit)
            )
        ]
    }


@router.get("/catalog")
def catalog(
    market: str = "DO-SDQ", limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)
):
    return {
        "market": market,
        "services": [
            svc.serialize(row)
            for row in db.scalars(
                select(Service)
                .where(Service.market_code == market, Service.active.is_(True))
                .order_by(Service.code)
                .limit(limit)
            )
        ],
    }


@router.get("/markets")
def markets():
    return {"markets": [{"code": "DO-SDQ", "currency": "DOP", "timezone": "America/Santo_Domingo"}]}


@router.post("/quotes", status_code=201, response_model=s.QuoteOutput)
def quote(
    payload: s.QuoteInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "quote.create",
        key,
        payload.model_dump(mode="json"),
        lambda: svc.create_quote(db, user, payload),
    )


@router.post("/bookings", status_code=201, response_model=s.BookingOutput)
def create_booking(
    payload: s.BookingInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "booking.create",
        key,
        payload.model_dump(mode="json"),
        lambda: svc.create_booking(db, user, payload.quote_id),
    )


@router.get("/bookings")
def bookings(
    limit: int = Query(50, ge=1, le=100),
    after: UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(Booking).where(Booking.customer_id == user.id)
    if after:
        query = query.where(Booking.id > after)
    rows = db.scalars(query.order_by(Booking.id).limit(limit + 1)).all()
    return {
        "items": [svc.booking_view(row) for row in rows[:limit]],
        "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
    }


@router.get("/bookings/{booking_id}", response_model=s.BookingOutput)
def booking(booking_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.booking_view(svc.booking_for(db, user, booking_id))


@router.post("/bookings/{booking_id}/cancel")
def cancel(
    booking_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    def action():
        row = svc.booking_for(db, user, booking_id, True)
        if row.customer_id != user.id:
            raise HTTPException(403, "Only the booking customer can cancel")
        svc.change(db, user, row, "CANCELLED", "BookingCancelled")
        for offer in db.scalars(select(Offer).where(Offer.booking_id == row.id)):
            offer.status = "CANCELLED"
        payment = db.scalar(select(Payment).where(Payment.booking_id == row.id).with_for_update())
        if payment and payment.status == "AUTHORIZED":
            from .payments import MockGateway

            MockGateway().cancel(payment.external_reference)
            payment.status = "CANCELLED"
        if row.provider_id:
            provider = svc.get(db, Provider, row.provider_id, True)
            provider.workload = max(0, provider.workload - 1)
        return svc.booking_view(row)

    return run(db, user, "booking.cancel:" + str(booking_id), key, {}, action)


@router.post("/payments/authorize", status_code=201)
def authorize(
    payload: s.AuthorizeInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "payment.authorize",
        key,
        payload.model_dump(mode="json"),
        lambda: svc.authorize(db, user, payload),
    )


@router.post("/bookings/{booking_id}/confirm")
@router.post("/bookings/{booking_id}/dispatch")
def dispatch(
    booking_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    return run(
        db, user, "dispatch:" + str(booking_id), key, {}, lambda: svc.dispatch(db, user, booking_id)
    )


@router.post("/provider/application", status_code=201)
def provider_application(
    payload: s.ProviderInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        if db.scalar(select(Provider).where(Provider.user_id == user.id)):
            raise HTTPException(409, "Provider application already exists")
        known = set(db.scalars(select(Service.code).where(Service.active.is_(True))))
        if not set(payload.services).issubset(known):
            raise HTTPException(422, "Unknown service")
        provider = Provider(user_id=user.id, status="SUBMITTED", **payload.model_dump())
        db.add(provider)
        user.roles = list(set(user.roles) | {"provider"})
        db.flush()
        emit(
            db,
            aggregate_type="provider",
            aggregate_id=str(provider.id),
            event_type="ProviderSubmitted",
            payload={"user_id": str(user.id)},
        )
        return svc.serialize(provider)

    return run(db, user, "provider.apply", key, payload.model_dump(), action)


@router.get("/providers/me")
@router.get("/provider/profile")
def provider_profile(user: User = Depends(require("provider.self")), db: Session = Depends(get_db)):
    return svc.serialize(svc.provider_for(db, user))


@router.put("/provider/availability")
def availability(
    payload: list[s.AvailabilityInput],
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    if len(payload) > 100 or any(row.end <= row.start for row in payload):
        raise HTTPException(422, "Invalid availability windows")

    def action():
        provider = svc.provider_for(db, user, True)
        provider.availability = [row.model_dump(mode="json") for row in payload]
        return {"items": provider.availability}

    return run(
        db,
        user,
        "provider.availability",
        key,
        [row.model_dump(mode="json") for row in payload],
        action,
    )


@router.put("/provider/status")
def online(
    payload: s.OnlineInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    def action():
        provider = svc.provider_for(db, user, True)
        if payload.online and provider.status != "APPROVED":
            raise HTTPException(409, "Approval is required before going online")
        provider.online = payload.online
        return svc.serialize(provider)

    return run(db, user, "provider.online", key, payload.model_dump(), action)


@router.put("/provider/location")
def location(
    payload: s.LocationInput,
    user: User = Depends(require("provider.location.update")),
    db: Session = Depends(get_db),
):
    import json

    from redis import Redis

    provider = svc.provider_for(db, user)
    if provider.status != "APPROVED":
        raise HTTPException(403, "Provider approval required")
    cache = Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
    cache.setex(
        "larimia:location:" + str(provider.id),
        120,
        json.dumps({**payload.model_dump(), "observed_at": now().isoformat()}),
    )
    return {"status": "accepted", "expires_in": 120}


@router.get("/dispatch/offers")
@router.get("/provider/offers")
def offers(
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    provider = svc.provider_for(db, user)
    rows = db.scalars(
        select(Offer)
        .where(
            Offer.provider_id == provider.id, Offer.status == "PENDING", Offer.expires_at > now()
        )
        .order_by(Offer.created_at.desc())
        .limit(limit)
    )
    return {
        "offers": [
            {**svc.serialize(row), "booking_version": svc.get(db, Booking, row.booking_id).version}
            for row in rows
        ]
    }


@router.post("/dispatch/offers/{offer_id}/accept")
@router.post("/provider/offers/{offer_id}/accept")
def accept(
    offer_id: UUID,
    payload: s.AcceptInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.offer.accept")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "offer.accept:" + str(offer_id),
        key,
        payload.model_dump(),
        lambda: svc.accept(db, user, offer_id, payload.booking_version),
    )


@router.post("/dispatch/offers/{offer_id}/decline")
def decline(
    offer_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    def action():
        provider = svc.provider_for(db, user)
        offer = svc.get(db, Offer, offer_id, True)
        if offer.provider_id != provider.id:
            raise HTTPException(404, "Offer not found")
        if offer.status != "PENDING":
            raise HTTPException(409, "Offer is no longer pending")
        offer.status = "DECLINED"
        return svc.serialize(offer)

    return run(db, user, "offer.decline:" + str(offer_id), key, {}, action)


@router.get("/provider/jobs")
def jobs(
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    provider = svc.provider_for(db, user)
    return {
        "items": [
            svc.booking_view(row)
            for row in db.scalars(
                select(Booking)
                .where(Booking.provider_id == provider.id)
                .order_by(Booking.created_at.desc())
                .limit(limit)
            )
        ]
    }


@router.post("/provider/jobs/{booking_id}/{action}")
def job(
    booking_id: UUID,
    action: str,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "job:" + str(booking_id) + ":" + action,
        key,
        {},
        lambda: svc.job_action(db, user, booking_id, action),
    )


@router.get("/provider/earnings")
@router.get("/providers/me/earnings")
def earnings(
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    provider = svc.provider_for(db, user)
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(Earning)
                .where(Earning.provider_id == provider.id)
                .order_by(Earning.created_at.desc())
                .limit(limit)
            )
        ]
    }


@router.post("/reviews", status_code=201)
def review(
    payload: s.ReviewInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("review.create")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "review.create",
        key,
        payload.model_dump(mode="json"),
        lambda: svc.review(db, user, payload),
    )


@router.post("/payments/refunds", status_code=201)
@router.post("/admin/refunds", status_code=201)
def refund(
    payload: s.RefundInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("payment.refund")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        "refund.create",
        key,
        payload.model_dump(mode="json"),
        lambda: svc.refund(db, user, payload, key),
    )


@router.get("/admin/bookings")
def admin_bookings(
    user: User = Depends(require("booking.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.booking_view(row)
            for row in db.scalars(select(Booking).order_by(Booking.created_at.desc()).limit(limit))
        ]
    }


@router.get("/dispatch/ops/board")
@router.get("/admin/dispatch")
def board(user: User = Depends(require("booking.dispatch")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Booking)
        .where(
            Booking.status.in_(
                [
                    "SEARCHING",
                    "OFFERED",
                    "ASSIGNED",
                    "PROVIDER_EN_ROUTE",
                    "ARRIVED",
                    "IN_PROGRESS",
                    "NO_PROVIDER_FOUND",
                ]
            )
        )
        .limit(100)
    ).all()
    return {
        "unassigned": [
            svc.booking_view(row) for row in rows if row.status in {"SEARCHING", "OFFERED"}
        ],
        "active": [svc.booking_view(row) for row in rows if row.provider_id],
        "late_risk": [],
        "recovery": [svc.booking_view(row) for row in rows if row.status == "NO_PROVIDER_FOUND"],
    }


@router.get("/admin/providers")
def admin_providers(
    user: User = Depends(require("provider.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {"items": [svc.serialize(row) for row in db.scalars(select(Provider).limit(limit))]}


@router.post("/admin/providers/{provider_id}/status")
def provider_status(
    provider_id: UUID,
    payload: s.StatusInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.application.review")),
    db: Session = Depends(get_db),
):
    def action():
        provider = svc.get(db, Provider, provider_id, True)
        transitions = {
            "DRAFT": {"SUBMITTED"},
            "SUBMITTED": {"UNDER_REVIEW"},
            "UNDER_REVIEW": {"ACTION_REQUIRED", "APPROVED", "REJECTED"},
            "ACTION_REQUIRED": {"SUBMITTED"},
            "APPROVED": {"SUSPENDED"},
            "SUSPENDED": {"UNDER_REVIEW"},
            "REJECTED": set(),
        }
        if payload.status not in transitions.get(provider.status, set()):
            raise HTTPException(409, "Invalid provider status transition")
        provider.status = payload.status
        if provider.status != "APPROVED":
            provider.online = False
        record_audit(
            db,
            actor=user.subject,
            action="provider.status",
            resource_type="provider",
            resource_id=str(provider.id),
            metadata={"status": payload.status, "reason": payload.reason},
        )
        emit(
            db,
            aggregate_type="provider",
            aggregate_id=str(provider.id),
            event_type="Provider" + payload.status.title(),
            payload={"user_id": str(provider.user_id), "status": provider.status},
        )
        return svc.serialize(provider)

    return run(db, user, "provider.status:" + str(provider_id), key, payload.model_dump(), action)


@router.get("/admin/payments")
def admin_payments(
    user: User = Depends(require("finance.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(limit))
        ]
    }


@router.get("/admin/finance")
def admin_finance(
    user: User = Depends(require("finance.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    from larimia.ledger.infrastructure_models import LedgerEntry, LedgerTransaction

    return {
        "entries": [
            svc.serialize(row)
            for row in db.scalars(
                select(LedgerEntry)
                .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
                .order_by(LedgerTransaction.created_at.desc())
                .limit(limit)
            )
        ],
        "earnings": [
            svc.serialize(row)
            for row in db.scalars(select(Earning).order_by(Earning.created_at.desc()).limit(limit))
        ],
    }


@router.get("/admin/audit")
def audit(
    user: User = Depends(require("audit.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
            )
        ]
    }


def create_case(kind, payload, key, user, db):
    def action():
        if payload.booking_id:
            svc.booking_for(db, user, payload.booking_id)
        row = Case(owner_id=user.id, kind=kind, **payload.model_dump())
        db.add(row)
        db.flush()
        emit(
            db,
            aggregate_type=kind,
            aggregate_id=str(row.id),
            event_type="SafetyIncidentCreated" if kind == "safety" else "SupportTicketCreated",
            payload={"user_id": str(user.id), "case_id": str(row.id)},
        )
        return svc.serialize(row)

    return run(db, user, "case.create:" + kind, key, payload.model_dump(mode="json"), action)


@router.post("/support", status_code=201)
def support(
    payload: s.CaseInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("case.create")),
    db: Session = Depends(get_db),
):
    return create_case("support", payload, key, user, db)


@router.post("/safety", status_code=201)
def safety(
    payload: s.CaseInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("case.create")),
    db: Session = Depends(get_db),
):
    return create_case("safety", payload, key, user, db)


@router.get("/support/ops/cases")
@router.get("/admin/support")
def support_list(
    user: User = Depends(require("support.ticket.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(select(Case).where(Case.kind == "support").limit(limit))
        ]
    }


@router.get("/safety/ops/incidents")
@router.get("/admin/safety")
def safety_list(
    user: User = Depends(require("safety.incident.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(select(Case).where(Case.kind == "safety").limit(limit))
        ]
    }


@router.get("/me/notifications")
def notifications(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        ]
    }


@router.post("/auth/refresh")
def refresh(payload: s.RefreshInput, db: Session = Depends(get_db)):
    if get_settings().auth_mode != "local":
        raise HTTPException(403, "Refresh is owned by the identity provider")
    import hashlib

    from .models import RefreshSession
    from .security import new_session

    token_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()
    initial = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash))
    if initial is None:
        raise HTTPException(401, "Refresh session invalid")
    user = db.scalar(
        select(User)
        .where(User.id == initial.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = db.scalar(
        select(RefreshSession)
        .where(RefreshSession.id == initial.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or row.revoked or row.expires_at <= now():
        raise HTTPException(401, "Refresh session invalid")
    user = svc.get(db, User, row.user_id)
    if not user.active:
        raise HTTPException(401, "Account disabled")
    row.revoked = True
    result = new_session(db, user, row.device_id)
    db.commit()
    return result


@router.post("/auth/logout", status_code=204)
def logout(
    payload: s.RefreshInput, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if get_settings().auth_mode != "local":
        raise HTTPException(403, "Logout is owned by the identity provider")
    import hashlib

    from .models import RefreshSession

    row = db.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.token_hash == hashlib.sha256(payload.refresh_token.encode()).hexdigest(),
            RefreshSession.user_id == user.id,
        )
        .with_for_update()
    )
    if row:
        row.revoked = True
    db.commit()
