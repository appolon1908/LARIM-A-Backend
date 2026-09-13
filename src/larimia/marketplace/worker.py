"""Durable local in-app delivery. PostgreSQL outbox remains the source of truth."""

import signal
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from larimia.shared.db import SessionLocal
from larimia.shared.events import OutboxEvent

from .models import Notification, User, now

running = True


def once() -> int:
    with SessionLocal.begin() as db:
        rows = db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            if row.payload.get("user_id"):
                user_id = UUID(row.payload["user_id"])
                if db.get(User, user_id):
                    db.execute(
                        insert(Notification)
                        .values(
                            event_id=row.id,
                            user_id=user_id,
                            kind=row.event_type,
                            payload=row.payload,
                        )
                        .on_conflict_do_nothing(index_elements=["event_id"])
                    )
            from larimia.config import get_settings

            from .models import EventDelivery

            if get_settings().event_transport == "azure":
                db.execute(
                    insert(EventDelivery)
                    .values(event_id=row.id)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
            row.published_at = now()
        return len(rows)


def stop(signum, frame):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        try:
            from .dispatch_worker import recover

            recover()
            once()
        except Exception:
            # No event is acknowledged on failure; transaction rollback preserves retryability.
            import logging

            logging.getLogger(__name__).error("Outbox batch failed; transaction rolled back")
        time.sleep(1)


if __name__ == "__main__":
    main()
