import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.shared.errors import ConflictError
from larimia.shared.idempotency_models import IdempotencyRecord


def request_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def reserve(db: Session, *, actor_subject: str, operation: str, key: str, payload: object):
    digest = request_hash(payload)
    existing = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_subject == actor_subject,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if existing:
        if existing.request_hash != digest:
            raise ConflictError(
                "IDEMPOTENCY_KEY_REUSED", "Same key was used with a different request"
            )
        if existing.status == "COMPLETED" and existing.response_json:
            return existing, json.loads(existing.response_json)
        if existing.status == "PROCESSING":
            raise ConflictError(
                "IDEMPOTENCY_IN_PROGRESS", "Request with this key is already processing"
            )
        existing.status = "PROCESSING"
        existing.response_json = None
        db.flush()
        return existing, None
    now = datetime.now(UTC)
    row = IdempotencyRecord(
        actor_subject=actor_subject,
        operation=operation,
        idempotency_key=key,
        request_hash=digest,
        status="PROCESSING",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    db.add(row)
    db.flush()
    return row, None


def complete(db: Session, row: IdempotencyRecord, response: dict) -> None:
    row.status = "COMPLETED"
    row.response_json = json.dumps(response, separators=(",", ":"), default=str)
    db.flush()


def fail(db: Session, row: IdempotencyRecord, error: dict) -> None:
    row.status = "FAILED"
    row.response_json = json.dumps(error, separators=(",", ":"), default=str)
    db.flush()
