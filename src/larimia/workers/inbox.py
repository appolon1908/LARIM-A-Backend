import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from larimia.marketplace.models import PaymentIntent
from larimia.shared.db import SessionLocal
from larimia.shared.events import InboxReceipt, emit


LEASE_SECONDS = 60
MAX_ATTEMPTS = 12
MAX_BACKOFF_SECONDS = 15 * 60


class UnsupportedInboxEvent(RuntimeError):
    pass


def _claim(limit: int) -> list[tuple[uuid.UUID, str]]:
    now = datetime.now(UTC)
    claimed: list[tuple[uuid.UUID, str]] = []
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(InboxReceipt)
                .where(
                    InboxReceipt.status.in_(["RECEIVED", "RETRY"]),
                    or_(
                        InboxReceipt.next_attempt_at.is_(None),
                        InboxReceipt.next_attempt_at <= now,
                    ),
                    or_(
                        InboxReceipt.locked_until.is_(None),
                        InboxReceipt.locked_until < now,
                    ),
                )
                .order_by(InboxReceipt.received_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for receipt in rows:
            token = uuid.uuid4().hex
            receipt.status = "PROCESSING"
            receipt.lock_token = token
            receipt.locked_until = now + timedelta(seconds=LEASE_SECONDS)
            receipt.attempts += 1
            claimed.append((receipt.id, token))
        db.commit()
    return claimed


def _load_claimed(
    db: Session,
    receipt_id: uuid.UUID,
    token: str,
) -> InboxReceipt | None:
    return db.scalar(
        select(InboxReceipt)
        .where(
            InboxReceipt.id == receipt_id,
            InboxReceipt.status == "PROCESSING",
            InboxReceipt.lock_token == token,
        )
        .with_for_update()
    )


def _canonical_payload(receipt: InboxReceipt) -> tuple[str, dict]:
    envelope = receipt.payload
    if not isinstance(envelope, dict):
        raise UnsupportedInboxEvent("Inbox envelope must be an object")
    raw = envelope.get("data")
    if not isinstance(raw, dict):
        raise UnsupportedInboxEvent("Inbox envelope data must be an object")

    event_type = raw.get("event_type") or raw.get("type")
    event_data = raw.get("data", raw)
    if not isinstance(event_type, str) or not isinstance(event_data, dict):
        raise UnsupportedInboxEvent("Canonical event_type and data are required")
    return event_type, event_data


def _apply_payment_event(
    db: Session,
    receipt: InboxReceipt,
    event_type: str,
    data: dict,
) -> None:
    status_by_type = {
        "payment.authorization_succeeded.v1": "AUTHORIZED",
        "payment.authorization_failed.v1": "AUTHORIZATION_FAILED",
        "payment.captured.v1": "CAPTURED",
        "payment.refunded.v1": "REFUNDED",
        "payment.dispute_opened.v1": "DISPUTED",
        "payment.dispute_closed.v1": "CAPTURED",
    }
    target_status = status_by_type.get(event_type)
    if target_status is None:
        raise UnsupportedInboxEvent(f"Unsupported payment event {event_type}")

    external_id = data.get("external_id") or data.get("payment_intent_external_id")
    if not isinstance(external_id, str) or not external_id:
        raise ValueError("Payment event external_id is required")

    intent = db.scalar(
        select(PaymentIntent)
        .where(PaymentIntent.external_id == external_id)
        .with_for_update()
    )
    if intent is None:
        # Providers can race the command response. Retrying is safer than
        # quarantining a valid event before the intent row is visible.
        raise LookupError(f"Payment intent {external_id!r} is not available")

    previous_status = intent.status
    intent.status = target_status
    intent.updated_at = datetime.now(UTC)
    emit(
        db,
        aggregate_type="payment_intent",
        aggregate_id=str(intent.id),
        event_type="payment.provider_event_applied.v1",
        payload={
            "payment_intent_id": str(intent.id),
            "booking_id": str(intent.booking_id),
            "provider_event_id": receipt.external_event_id,
            "provider": receipt.provider,
            "canonical_event_type": event_type,
            "previous_status": previous_status,
            "status": target_status,
        },
    )


def _apply(db: Session, receipt: InboxReceipt) -> None:
    event_type, data = _canonical_payload(receipt)
    if receipt.provider.startswith("payments:"):
        _apply_payment_event(db, receipt, event_type, data)
        return
    raise UnsupportedInboxEvent(
        f"No inbox processor is certified for {receipt.provider!r}"
    )


def _mark_completed(receipt: InboxReceipt) -> None:
    receipt.status = "COMPLETED"
    receipt.processed_at = datetime.now(UTC)
    receipt.lock_token = None
    receipt.locked_until = None
    receipt.next_attempt_at = None
    receipt.last_error = None


def _mark_failure(receipt: InboxReceipt, error: Exception) -> None:
    now = datetime.now(UTC)
    receipt.lock_token = None
    receipt.locked_until = None
    receipt.last_error = f"{type(error).__name__}: {str(error)[:1000]}"

    if isinstance(error, UnsupportedInboxEvent):
        receipt.status = "QUARANTINED"
        receipt.next_attempt_at = None
        return
    if receipt.attempts >= MAX_ATTEMPTS:
        receipt.status = "DEAD"
        receipt.next_attempt_at = None
        return

    backoff = min(2 ** min(receipt.attempts, 10), MAX_BACKOFF_SECONDS)
    receipt.status = "RETRY"
    receipt.next_attempt_at = now + timedelta(seconds=backoff)


def process_batch(limit: int = 100) -> int:
    claims = _claim(limit)
    processed = 0
    for receipt_id, token in claims:
        with SessionLocal() as db:
            receipt = _load_claimed(db, receipt_id, token)
            if receipt is None:
                continue
            try:
                _apply(db, receipt)
                _mark_completed(receipt)
                db.commit()
                processed += 1
            except Exception as exc:
                db.rollback()
                receipt = _load_claimed(db, receipt_id, token)
                if receipt is None:
                    continue
                _mark_failure(receipt, exc)
                db.commit()
    return processed
