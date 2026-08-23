import json
from datetime import datetime, timezone
import redis.asyncio as redis
from sqlalchemy import select
from larimia.config import get_settings
from larimia.shared.db import SessionLocal
from larimia.shared.events import OutboxEvent

def topics(event: OutboxEvent):
    out = []
    if event.aggregate_type == "booking":
        out.extend([f"booking:{event.aggregate_id}", "ops:dispatch"])
    provider_id = event.payload.get("provider_id") if isinstance(event.payload, dict) else None
    if provider_id:
        out.append(f"provider:{provider_id}:offers")
    return out

async def publish_batch(limit: int = 100):
    url = get_settings().websocket_redis_url
    if not url:
        return 0
    client = redis.from_url(url, decode_responses=True)
    count = 0
    try:
        with SessionLocal() as db:
            rows = list(db.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ))
            for event in rows:
                envelope = {
                    "id": str(event.id),
                    "type": event.event_type,
                    "version": 1,
                    "occurred_at": event.created_at.isoformat(),
                    "aggregate_id": event.aggregate_id,
                    "data": event.payload,
                }
                for topic in topics(event):
                    await client.publish(topic, json.dumps(envelope, default=str))
                event.published_at = datetime.now(timezone.utc)
                count += 1
            db.commit()
    finally:
        await client.aclose()
    return count
