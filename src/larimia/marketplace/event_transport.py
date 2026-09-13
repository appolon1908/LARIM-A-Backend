import json
from datetime import timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select

from larimia.config import get_settings
from larimia.shared.db import SessionLocal
from larimia.shared.events import OutboxEvent

from .models import EventDelivery, now


class EventTransport(Protocol):
    def publish(self, event_id: str, event_type: str, payload: dict) -> None: ...


class AzureServiceBusTransport:
    def publish(self, event_id: str, event_type: str, payload: dict) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.servicebus import ServiceBusClient, ServiceBusMessage

        settings = get_settings()
        with DefaultAzureCredential(
            managed_identity_client_id=settings.azure_client_id or None
        ) as credential:
            with ServiceBusClient(
                settings.service_bus_namespace, credential, retry_total=2
            ) as client:
                with client.get_queue_sender(queue_name=settings.service_bus_queue) as sender:
                    sender.send_messages(
                        ServiceBusMessage(
                            json.dumps({"id": event_id, "type": event_type, "data": payload}),
                            message_id=event_id,
                            correlation_id=event_id,
                            content_type="application/json",
                        ),
                        timeout=10,
                    )


def publish_once(transport: EventTransport | None = None) -> bool:
    settings = get_settings()
    if settings.event_transport != "azure" and transport is None:
        return False
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(EventDelivery)
            .where(
                EventDelivery.status.in_(["PENDING", "LEASED"]), EventDelivery.available_at <= now()
            )
            .order_by(EventDelivery.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not row:
            return False
        event = db.get(OutboxEvent, row.event_id)
        if event is None:
            raise RuntimeError("Delivery references missing outbox event")
        row.status = "LEASED"
        row.lease_token = str(uuid4())
        row.available_at = now() + timedelta(minutes=2)
        identity, token, event_id, event_type, payload = (
            row.id,
            row.lease_token,
            str(event.id),
            event.event_type,
            event.payload,
        )
    error = None
    try:
        (transport or AzureServiceBusTransport()).publish(event_id, event_type, payload)
    except Exception as exc:
        error = type(exc).__name__
    with SessionLocal.begin() as db:
        row = db.scalar(select(EventDelivery).where(EventDelivery.id == identity).with_for_update())
        if row is None or row.lease_token != token:
            return False
        row.attempts += 1
        row.last_error = error
        row.status = (
            "DELIVERED" if error is None else "DEAD_LETTER" if row.attempts >= 10 else "PENDING"
        )
        row.available_at = now() + timedelta(seconds=min(3600, 2**row.attempts))
        row.lease_token = None
    return error is None


def main():
    import signal
    import time

    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        try:
            publish_once()
        except Exception:
            import logging

            logging.getLogger(__name__).error("Event publisher unavailable; durable lease retained")
        time.sleep(1)


if __name__ == "__main__":
    main()
