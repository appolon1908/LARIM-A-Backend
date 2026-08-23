import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from larimia.shared.errors import ConflictError
from larimia.shared.idempotency_models import IdempotencyRecord


IDEMPOTENCY_TTL = timedelta(hours=24)


def request_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _load_locked(
    db: Session,
    *,
    actor_subject: str,
    operation: str,
    key: str,
) -> IdempotencyRecord:
    row = db.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.actor_subject == actor_subject,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("Idempotency reservation disappeared after insert conflict")
    return row


def reserve(
    db: Session,
    *,
    actor_subject: str,
    operation: str,
    key: str,
    payload: object,
) -> tuple[IdempotencyRecord, dict[str, Any] | None]:
    digest = request_hash(payload)
    now = datetime.now(UTC)
    record_id = uuid.uuid4()

    inserted_id = db.scalar(
        insert(IdempotencyRecord)
        .values(
            id=record_id,
            actor_subject=actor_subject,
            operation=operation,
            idempotency_key=key,
            request_hash=digest,
            status="PROCESSING",
            created_at=now,
            expires_at=now + IDEMPOTENCY_TTL,
        )
        .on_conflict_do_nothing(
            index_elements=["actor_subject", "operation", "idempotency_key"]
        )
        .returning(IdempotencyRecord.id)
    )

    if inserted_id is not None:
        row = db.get(IdempotencyRecord, inserted_id)
        if row is None:
            raise RuntimeError("Idempotency reservation could not be loaded")
        return row, None

    row = _load_locked(
        db,
        actor_subject=actor_subject,
        operation=operation,
        key=key,
    )

    if row.request_hash != digest:
        raise ConflictError(
            "IDEMPOTENCY_KEY_REUSED",
            "Same idempotency key was used with a different request",
        )

    if row.expires_at <= now:
        row.status = "PROCESSING"
        row.response_json = None
        row.created_at = now
        row.expires_at = now + IDEMPOTENCY_TTL
        db.flush()
        return row, None

    if row.status == "COMPLETED" and row.response_json:
        return row, json.loads(row.response_json)

    if row.status == "PROCESSING":
        raise ConflictError(
            "IDEMPOTENCY_IN_PROGRESS",
            "Request with this idempotency key is already processing",
        )

    # FAILED reservations may be retried with the same payload/key.
    row.status = "PROCESSING"
    row.response_json = None
    db.flush()
    return row, None


def complete(db: Session, row: IdempotencyRecord, response: dict[str, Any]) -> None:
    row.status = "COMPLETED"
    row.response_json = json.dumps(
        response,
        separators=(",", ":"),
        default=str,
    )
    db.flush()


def fail(db: Session, row: IdempotencyRecord, error: dict[str, Any]) -> None:
    row.status = "FAILED"
    row.response_json = json.dumps(
        error,
        separators=(",", ":"),
        default=str,
    )
    db.flush()
