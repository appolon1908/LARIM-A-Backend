import json
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy import or_, select

from larimia.config import get_settings
from larimia.shared.db import SessionLocal
from larimia.shared.events import OutboxEvent


LEASE_SECONDS = 60
MAX_ATTEMPTS = 12
MAX_BACKOFF_SECONDS = 15 * 60


def topics(event: OutboxEvent) -> list[str]:
    output = [f"events:{event.aggregate_type}"]
    if event.aggregate_type == "booking":
        output.extend([f"booking:{event.aggregate_id}", "ops:dispatch"])

    provider_id = (
        event.payload.get("provider_id")
        if isinstance(event.payload, dict)
        else None
    )
    if provider_id:
        output.append(f"provider:{provider_id}:offers")
    return sorted(set(output))


def stream_key(topic: str) -> str:
    return f"realtime:{topic}"


def _claim(limit: int) -> list[tuple[uuid.UUID, str]]:
    now = datetime.now(UTC)
    claimed: list[tuple[uuid.UUID, str]] = []
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.status.in_(["PENDING", "RETRY"]),
                    or_(
                        OutboxEvent.next_attempt_at.is_(None),
                        OutboxEvent.next_attempt_at <= now,
                    ),
                    or_(
                        OutboxEvent.locked_until.is_(None),
                        OutboxEvent.locked_until < now,
                    ),
                )
                .order_by(OutboxEvent.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for event in rows:
            token = uuid.uuid4().hex
            event.status = "PROCESSING"
            event.lock_token = token
            event.locked_until = now + timedelta(seconds=LEASE_SECONDS)
            event.attempts += 1
            claimed.append((event.id, token))
        db.commit()
    return claimed


def _load_claimed(event_id: uuid.UUID, token: str) -> OutboxEvent | None:
    with SessionLocal() as db:
        event = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == "PROCESSING",
                OutboxEvent.lock_token == token,
            )
        )
        if event is None:
            return None
        db.expunge(event)
        return event


def _mark_published(event_id: uuid.UUID, token: str) -> bool:
    with SessionLocal() as db:
        event = db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == "PROCESSING",
                OutboxEvent.lock_token == token,
            )
            .with_for_update()
        )
        if event is None:
            return False
        event.status = "PUBLISHED"
        event.published_at = datetime.now(UTC)
        event.lock_token = None
        event.locked_until = None
        event.next_attempt_at = None
        event.last_error = None
        db.commit()
        return True


def _mark_failed(event_id: uuid.UUID, token: str, error: Exception) -> bool:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        event = db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == "PROCESSING",
                OutboxEvent.lock_token == token,
            )
            .with_for_update()
        )
        if event is None:
            return False
        event.lock_token = None
        event.locked_until = None
        event.last_error = f"{type(error).__name__}: {str(error)[:500]}"

        if event.attempts >= MAX_ATTEMPTS:
            event.status = "DEAD"
            event.next_attempt_at = None
        else:
            backoff = min(2 ** min(event.attempts, 10), MAX_BACKOFF_SECONDS)
            event.status = "RETRY"
            event.next_attempt_at = now + timedelta(seconds=backoff)
        db.commit()
        return True


async def publish_batch(limit: int = 100) -> int:
    settings = get_settings()
    if not settings.websocket_redis_url:
        return 0

    claims = _claim(limit)
    if not claims:
        return 0

    client = redis.from_url(
        settings.websocket_redis_url,
        decode_responses=True,
    )
    published = 0
    try:
        for event_id, token in claims:
            event = _load_claimed(event_id, token)
            if event is None:
                continue

            envelope = {
                "id": str(event.id),
                "type": event.event_type,
                "version": 1,
                "occurred_at": event.created_at.isoformat(),
                "aggregate_id": event.aggregate_id,
                "data": event.payload,
            }
            try:
                encoded = json.dumps(
                    envelope,
                    default=str,
                    separators=(",", ":"),
                )
                for topic in topics(event):
                    await client.xadd(
                        stream_key(topic),
                        {"event": encoded},
                        maxlen=settings.realtime_stream_maxlen,
                        approximate=True,
                    )
                if _mark_published(event_id, token):
                    published += 1
            except Exception as exc:
                _mark_failed(event_id, token, exc)
    finally:
        await client.aclose()
    return published
