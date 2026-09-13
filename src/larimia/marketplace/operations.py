import base64
import hashlib
import hmac
import json
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.shared.audit import record_audit
from larimia.shared.db import get_db
from larimia.shared.events import InboxReceipt, emit
from larimia.shared.idempotency import require_idempotency_key

from . import schemas as s
from . import service as svc
from .models import (
    Case,
    Conversation,
    Document,
    Earning,
    Message,
    Payment,
    Payout,
    Promotion,
    Provider,
    Service,
    User,
    now,
)
from .models import MarketplaceBooking as Booking
from .routes import run
from .security import allowed, current_user, require
from .storage import storage

router = APIRouter()


@router.post("/admin/payouts", status_code=201)
def schedule_payout(
    payload: s.PayoutInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("finance.payout.approve")),
    db: Session = Depends(get_db),
):
    def action():
        provider = svc.get(db, Provider, payload.provider_id, True)
        if provider.status != "APPROVED":
            raise HTTPException(409, "Provider must be approved for payouts")
        earnings = db.scalars(
            select(Earning)
            .where(
                Earning.provider_id == provider.id,
                Earning.status == "PENDING",
                Earning.currency == payload.currency,
            )
            .with_for_update()
        ).all()
        total = sum(row.amount_minor for row in earnings)
        if total <= 0:
            raise HTTPException(409, "No payable earnings")
        payout = Payout(
            provider_id=provider.id,
            currency=payload.currency,
            amount_minor=total,
            earning_ids=[str(row.id) for row in earnings],
            approved_by=user.subject,
        )
        db.add(payout)
        db.flush()
        for row in earnings:
            row.status = "RESERVED"
        record_audit(
            db,
            actor=user.subject,
            action="PayoutScheduled",
            resource_type="payout",
            resource_id=str(payout.id),
        )
        emit(
            db,
            aggregate_type="payout",
            aggregate_id=str(payout.id),
            event_type="PayoutScheduled",
            payload={"user_id": str(provider.user_id), "payout_id": str(payout.id)},
        )
        return svc.serialize(payout)

    return run(db, user, "payout.create", key, payload.model_dump(mode="json"), action)


@router.post("/admin/payouts/{payout_id}/complete")
def complete_payout(
    payout_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("finance.payout.approve")),
    db: Session = Depends(get_db),
):
    def action():
        payout = svc.get(db, Payout, payout_id, True)
        if payout.status != "SCHEDULED":
            raise HTTPException(409, "Payout already processed")
        # Explicit simulation: real banking requires a reconciled gateway implementation.
        payout.external_reference = "mock_payout_" + str(payout.id)
        payout.status = "COMPLETED"
        for row in db.scalars(
            select(Earning)
            .where(Earning.id.in_([UUID(value) for value in payout.earning_ids]))
            .with_for_update()
        ):
            row.status = "PAID"
        svc.journal(
            db,
            "payout",
            str(payout.id),
            payout.currency,
            [
                ("provider:" + str(payout.provider_id), "DEBIT", payout.amount_minor),
                ("processor", "CREDIT", payout.amount_minor),
            ],
        )
        record_audit(
            db,
            actor=user.subject,
            action="PayoutCompleted",
            resource_type="payout",
            resource_id=str(payout.id),
        )
        return svc.serialize(payout)

    return run(db, user, "payout.complete:" + str(payout_id), key, {}, action)


@router.get("/provider/payouts")
@router.get("/providers/me/payouts")
def payouts(
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    provider = svc.provider_for(db, user)
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(Payout).where(Payout.provider_id == provider.id).limit(limit)
            )
        ]
    }


@router.get("/admin/payouts")
def admin_payouts(
    user: User = Depends(require("finance.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(select(Payout).order_by(Payout.created_at.desc()).limit(limit))
        ]
    }


@router.get("/finance/reconciliation-breaks")
def reconciliation(user: User = Depends(require("finance.read")), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            text(
                "SELECT transaction_id, sum(CASE WHEN direction='DEBIT' THEN "
                "amount_minor ELSE -amount_minor END) balance FROM ledger_entries "
                "GROUP BY transaction_id HAVING sum(CASE WHEN direction='DEBIT' "
                "THEN amount_minor ELSE -amount_minor END) <> 0 LIMIT 100"
            )
        )
        .mappings()
        .all()
    )
    return {"items": [dict(row) for row in rows]}


@router.post("/conversations", status_code=201)
def conversation(
    payload: s.ConversationInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        booking = svc.booking_for(db, user, payload.booking_id, True)
        if not booking.provider_id:
            raise HTTPException(409, "Conversation requires assignment")
        row = db.scalar(select(Conversation).where(Conversation.booking_id == booking.id))
        if not row:
            row = Conversation(booking_id=booking.id)
            db.add(row)
            db.flush()
        return svc.serialize(row)

    return run(db, user, "conversation.create", key, payload.model_dump(mode="json"), action)


def conversation_for(db, user, identity):
    row = svc.get(db, Conversation, identity)
    svc.booking_for(db, user, row.booking_id)
    return row


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(
    conversation_id: UUID,
    payload: s.MessageInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        conversation = conversation_for(db, user, conversation_id)
        booking = svc.get(db, Booking, conversation.booking_id)
        provider = svc.get(db, Provider, booking.provider_id)
        row = Message(conversation_id=conversation_id, sender_id=user.id, body=payload.body)
        db.add(row)
        db.flush()
        for recipient in {booking.customer_id, provider.user_id}:
            emit(
                db,
                aggregate_type="conversation",
                aggregate_id=str(conversation_id),
                event_type="ChatMessageCreated",
                payload={
                    "conversation_id": str(conversation_id),
                    "message_id": str(row.id),
                    "user_id": str(recipient),
                },
            )
        return svc.serialize(row)

    return run(db, user, "message.send:" + str(conversation_id), key, payload.model_dump(), action)


@router.get("/conversations/{conversation_id}/messages")
def messages(
    conversation_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    after: UUID | None = None,
):
    conversation_for(db, user, conversation_id)
    query = select(Message).where(Message.conversation_id == conversation_id)
    if after:
        query = query.where(Message.id > after)
    rows = db.scalars(query.order_by(Message.id).limit(limit + 1)).all()
    return {
        "items": [svc.serialize(row) for row in rows[:limit]],
        "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
    }


@router.post("/provider/documents", status_code=201)
def document(
    payload: s.DocumentInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    def action():
        from pathlib import PurePath

        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(422, "Invalid file encoding") from exc
        signatures = {
            "image/png": (b"\x89PNG\r\n\x1a\n", {".png"}),
            "image/jpeg": (b"\xff\xd8\xff", {".jpg", ".jpeg"}),
            "application/pdf": (b"%PDF-", {".pdf"}),
        }
        signature, extensions = signatures[payload.content_type]
        if (
            not content.startswith(signature)
            or PurePath(payload.filename).suffix.lower() not in extensions
            or len(content) > 512000
        ):
            raise HTTPException(422, "File type or size rejected")
        if payload.booking_id:
            booking = svc.booking_for(db, user, payload.booking_id)
            provider = svc.provider_for(db, user)
            if booking.provider_id != provider.id or provider.status != "APPROVED":
                raise HTTPException(403, "Evidence must belong to assigned approved provider")
        row = Document(
            owner_id=user.id,
            booking_id=payload.booking_id,
            storage_key=str(uuid4()),
            content_type=payload.content_type,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        storage().put(row.storage_key, content)
        db.add(row)
        db.flush()
        return {k: v for k, v in svc.serialize(row).items() if k != "storage_key"}

    return run(
        db,
        user,
        "document.create",
        key,
        {"digest": hashlib.sha256(payload.model_dump_json().encode()).hexdigest()},
        action,
    )


@router.get("/provider/documents")
def documents(
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            {k: v for k, v in svc.serialize(row).items() if k != "storage_key"}
            for row in db.scalars(select(Document).where(Document.owner_id == user.id).limit(limit))
        ]
    }


@router.get("/provider/documents/{document_id}/download")
def download(document_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = svc.get(db, Document, document_id)
    if row.owner_id != user.id and not allowed(user, "provider.application.review"):
        raise HTTPException(404, "Document not found")
    return Response(
        storage().get(row.storage_key),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="document"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/admin/support/{case_id}/resolve")
def resolve_support(
    case_id: UUID,
    payload: s.ResolutionInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("support.ticket.manage")),
    db: Session = Depends(get_db),
):
    return resolve_case("support", case_id, payload, key, user, db)


@router.post("/admin/safety/{case_id}/resolve")
def resolve_safety(
    case_id: UUID,
    payload: s.ResolutionInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("safety.incident.manage")),
    db: Session = Depends(get_db),
):
    return resolve_case("safety", case_id, payload, key, user, db)


def resolve_case(kind, identity, payload, key, user, db):
    def action():
        row = svc.get(db, Case, identity, True)
        if row.kind != kind:
            raise HTTPException(404, "Case not found")
        if row.status != "OPEN":
            raise HTTPException(409, "Case already resolved")
        row.status = "RESOLVED"
        row.resolution = payload.resolution
        record_audit(
            db,
            actor=user.subject,
            action=kind + ".resolved",
            resource_type=kind,
            resource_id=str(row.id),
        )
        return svc.serialize(row)

    return run(db, user, kind + ".resolve:" + str(identity), key, payload.model_dump(), action)


@router.get("/admin/dashboard")
def dashboard(user: User = Depends(require("booking.read")), db: Session = Depends(get_db)):
    return {
        "bookings": {
            status: count
            for status, count in db.execute(
                select(Booking.status, func.count()).group_by(Booking.status)
            )
        },
        "providers": {
            status: count
            for status, count in db.execute(
                select(Provider.status, func.count()).group_by(Provider.status)
            )
        },
    }


@router.get("/admin/customers")
def customers(
    user: User = Depends(require("admin.user.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(select(User).order_by(User.created_at.desc()).limit(limit))
        ]
    }


@router.post("/admin/catalog", status_code=201)
def create_service(
    payload: s.ServiceInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("catalog.manage")),
    db: Session = Depends(get_db),
):
    def action():
        if db.scalar(select(Service).where(Service.code == payload.code)):
            raise HTTPException(409, "Service already exists")
        row = Service(**payload.model_dump())
        db.add(row)
        db.flush()
        record_audit(
            db,
            actor=user.subject,
            action="catalog.created",
            resource_type="service",
            resource_id=str(row.id),
        )
        return svc.serialize(row)

    return run(db, user, "catalog.create", key, payload.model_dump(), action)


@router.put("/admin/pricing/{service_id}")
def pricing(
    service_id: UUID,
    payload: s.PricingInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("pricing.manage")),
    db: Session = Depends(get_db),
):
    def action():
        row = svc.get(db, Service, service_id, True)
        for name, value in payload.model_dump().items():
            setattr(row, name, value)
        row.version += 1
        record_audit(
            db,
            actor=user.subject,
            action="pricing.changed",
            resource_type="service",
            resource_id=str(row.id),
            metadata={"version": row.version},
        )
        return svc.serialize(row)

    return run(db, user, "pricing.update:" + str(service_id), key, payload.model_dump(), action)


@router.post("/admin/promotions", status_code=201)
def promotion(
    payload: s.PromotionInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("pricing.manage")),
    db: Session = Depends(get_db),
):
    def action():
        if payload.expires_at <= now() or db.scalar(
            select(Promotion).where(Promotion.code == payload.code)
        ):
            raise HTTPException(409, "Promotion expired or code already exists")
        row = Promotion(**payload.model_dump())
        db.add(row)
        db.flush()
        record_audit(
            db,
            actor=user.subject,
            action="promotion.created",
            resource_type="promotion",
            resource_id=str(row.id),
        )
        return svc.serialize(row)

    return run(db, user, "promotion.create", key, payload.model_dump(mode="json"), action)


@router.post("/webhooks/payments", status_code=202)
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    # Webhooks are receipts to reconcile, never authority to invent a capture or ledger entry.
    secret = get_settings().payment_webhook_secret
    if not secret:
        raise HTTPException(503, "Payment webhook is not configured")
    raw = await request.body()
    timestamp = request.headers.get("X-Webhook-Timestamp", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("expired")
    except ValueError as exc:
        raise HTTPException(401, "Invalid webhook timestamp") from exc
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Webhook-Signature", "")):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = json.loads(raw)
        event_id = payload["id"]
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 255:
            raise ValueError("invalid event id")
        payment_id = UUID(payload["payment_id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "Invalid webhook schema") from exc
    from .commands import command

    def action():
        payment = svc.get(db, Payment, payment_id)
        receipt = InboxReceipt(
            provider="payments",
            external_event_id=event_id,
            payload={"payment_id": str(payment.id), "body_sha256": hashlib.sha256(raw).hexdigest()},
            processed_at=now(),
        )
        db.add(receipt)
        record_audit(
            db,
            actor="payment_gateway",
            action="PaymentWebhookReceived",
            resource_type="payment",
            resource_id=str(payment.id),
        )
        return {"status": "RECEIVED", "reconciliation_required": True}

    return command(
        db, "payment_gateway", "webhook", event_id, hashlib.sha256(raw).hexdigest(), action
    )


@router.put("/admin/users/{user_id}/roles")
def user_roles(
    user_id: UUID,
    payload: s.RoleUpdate,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("admin.user.manage")),
    db: Session = Depends(get_db),
):
    from .security import PERMISSIONS

    if not set(payload.roles).issubset(PERMISSIONS):
        raise HTTPException(422, "Unknown role")
    if user_id == user.id:
        raise HTTPException(409, "Administrators cannot change their own roles")

    def action():
        row = svc.get(db, User, user_id, True)
        previous = row.roles
        row.roles = payload.roles
        record_audit(
            db,
            actor=user.subject,
            action="UserRolesChanged",
            resource_type="user",
            resource_id=str(row.id),
            metadata={"previous": previous, "roles": row.roles, "reason": payload.reason},
        )
        return svc.serialize(row)

    return run(db, user, "user.roles:" + str(user_id), key, payload.model_dump(), action)


@router.post("/me/blocks", status_code=201)
def block(
    payload: s.BlockInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    from .models import Block

    def action():
        svc.get(db, Provider, payload.provider_id)
        row = db.scalar(
            select(Block).where(
                Block.provider_id == payload.provider_id, Block.customer_id == user.id
            )
        )
        if not row:
            row = Block(provider_id=payload.provider_id, customer_id=user.id)
            db.add(row)
            db.flush()
        return svc.serialize(row)

    return run(db, user, "customer.block", key, payload.model_dump(mode="json"), action)


@router.put("/provider/services")
def provider_services(
    payload: s.ProviderServices,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    def action():
        provider = svc.provider_for(db, user, True)
        services = db.scalars(
            select(Service).where(Service.code.in_(payload.services), Service.active.is_(True))
        ).all()
        if len(services) != len(set(payload.services)) or any(
            not set(row.required_skills).issubset(provider.skills) for row in services
        ):
            raise HTTPException(422, "Service unavailable or required skill not verified")
        provider.services = payload.services
        return svc.serialize(provider)

    return run(db, user, "provider.services", key, payload.model_dump(), action)


@router.get("/provider/services")
def get_provider_services(
    user: User = Depends(require("provider.self")), db: Session = Depends(get_db)
):
    provider = svc.provider_for(db, user)
    return {"services": provider.services, "verified_skills": provider.skills}


@router.get("/provider/application")
def application(user: User = Depends(require("provider.self")), db: Session = Depends(get_db)):
    return svc.serialize(svc.provider_for(db, user))


@router.get("/provider/availability")
def provider_availability(
    user: User = Depends(require("provider.self")), db: Session = Depends(get_db)
):
    return {"items": svc.provider_for(db, user).availability}


@router.get("/bookings/{booking_id}/receipt")
def receipt(booking_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = svc.booking_for(db, user, booking_id)
    payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id))
    return {
        "booking_id": booking.id,
        "pricing": booking.snapshot,
        "payment": svc.serialize(payment) if payment else None,
    }


@router.get("/bookings/{booking_id}/location")
def last_location(
    booking_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    from redis import Redis

    booking = svc.booking_for(db, user, booking_id)
    if not booking.provider_id or booking.status not in {
        "ASSIGNED",
        "PROVIDER_EN_ROUTE",
        "ARRIVED",
        "IN_PROGRESS",
    }:
        raise HTTPException(404, "Live provider location is not available")
    cache = Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
    raw = cache.get("larimia:location:" + str(booking.provider_id))
    return {"location": json.loads(raw) if isinstance(raw, (str, bytes)) else None}


@router.get("/admin/catalog")
@router.get("/admin/pricing")
def admin_catalog(
    user: User = Depends(require("catalog.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {"items": [svc.serialize(row) for row in db.scalars(select(Service).limit(limit))]}


@router.get("/admin/promotions")
def promotions(
    user: User = Depends(require("pricing.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {"items": [svc.serialize(row) for row in db.scalars(select(Promotion).limit(limit))]}


@router.post("/admin/dispatch/{booking_id}")
def manual_dispatch(
    booking_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.dispatch")),
    db: Session = Depends(get_db),
):
    return run(
        db, user, "dispatch:" + str(booking_id), key, {}, lambda: svc.dispatch(db, user, booking_id)
    )


@router.get("/admin/events/dlq")
def event_dead_letters(
    user: User = Depends(require("integration.replay")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    from .models import EventDelivery

    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(EventDelivery).where(EventDelivery.status == "DEAD_LETTER").limit(limit)
            )
        ]
    }


@router.post("/admin/events/dlq/{delivery_id}/replay")
def replay_event(
    delivery_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("integration.replay")),
    db: Session = Depends(get_db),
):
    from .models import EventDelivery

    def action():
        row = svc.get(db, EventDelivery, delivery_id, True)
        if row.status != "DEAD_LETTER":
            raise HTTPException(409, "Only dead letters may be replayed")
        row.status = "PENDING"
        row.attempts = 0
        row.available_at = now()
        row.lease_token = None
        record_audit(
            db,
            actor=user.subject,
            action="IntegrationEventReplayed",
            resource_type="event_delivery",
            resource_id=str(row.id),
        )
        return svc.serialize(row)

    return run(db, user, "event.replay:" + str(delivery_id), key, {}, action)


@router.post("/bookings/{booking_id}/disputes", status_code=201)
def open_dispute(
    booking_id: UUID,
    payload: s.MessageInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("booking.create")),
    db: Session = Depends(get_db),
):
    def action():
        booking = svc.booking_for(db, user, booking_id, True)
        if booking.customer_id != user.id:
            raise HTTPException(403, "Only the customer may open this dispute")
        svc.change(db, user, booking, "DISPUTED", "DisputeOpened")
        case = Case(owner_id=user.id, booking_id=booking.id, kind="dispute", body=payload.body)
        db.add(case)
        db.flush()
        return svc.serialize(case)

    return run(db, user, "dispute:" + str(booking_id), key, payload.model_dump(), action)


@router.get("/admin/providers/{provider_id}/documents")
def review_documents(
    provider_id: UUID,
    user: User = Depends(require("provider.application.review")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    provider = svc.get(db, Provider, provider_id)
    return {
        "items": [
            {k: v for k, v in svc.serialize(row).items() if k != "storage_key"}
            for row in db.scalars(
                select(Document).where(Document.owner_id == provider.user_id).limit(limit)
            )
        ]
    }


@router.get("/admin/legacy/bookings")
def legacy_bookings(
    user: User = Depends(require("admin.user.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    from larimia.bookings.infrastructure.models import Booking as LegacyBooking

    return {
        "migration_required": True,
        "items": [svc.serialize(row) for row in db.scalars(select(LegacyBooking).limit(limit))],
    }
