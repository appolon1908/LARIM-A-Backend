"""One database transaction owns a command, its response, audit and outbox."""

import hashlib
import json
from collections.abc import Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from larimia.shared.idempotency_service import begin_idempotent


def command(
    db: Session, actor: str, operation: str, key: str, payload: object, action: Callable[[], dict]
) -> dict:
    lock = int.from_bytes(
        hashlib.sha256(f"{actor}:{operation}:{key}".encode()).digest()[:8], "big", signed=True
    )
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        record = begin_idempotent(
            db, actor_subject=actor, operation=operation, key=key, payload=payload
        )
        if record.status == "COMPLETED":
            if record.response_json is None:
                raise RuntimeError("Completed idempotency record is missing its response")
            return json.loads(record.response_json)
        result = jsonable_encoder(action())
        record.status = "COMPLETED"
        record.response_json = json.dumps(result)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
