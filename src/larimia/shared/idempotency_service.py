import hashlib, json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from larimia.shared.idempotency_models import IdempotencyRecord
from larimia.shared.errors import ConflictError

def request_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()

def begin_idempotent(
    db: Session,
    *,
    actor_subject: str,
    operation: str,
    key: str,
    payload: object,
) -> IdempotencyRecord:
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
            raise ConflictError("IDEMPOTENCY_KEY_REUSED", "Same key was used with a different request")
        return existing

    now = datetime.now(timezone.utc)
    record = IdempotencyRecord(
        actor_subject=actor_subject,
        operation=operation,
        idempotency_key=key,
        request_hash=digest,
        status="PROCESSING",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    db.add(record)
    db.flush()
    return record
