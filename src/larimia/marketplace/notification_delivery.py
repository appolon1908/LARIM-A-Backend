"""Transactional fanout and leased delivery; vendor I/O never holds a DB transaction."""

from dataclasses import dataclass
from datetime import timedelta
from string import Template
from typing import Protocol
from uuid import uuid4

import httpx
from sqlalchemy import select

from larimia.config import get_settings
from larimia.shared.db import SessionLocal

from .models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
    User,
    now,
)

CHANNELS = {"email", "sms", "push"}
VARIABLES = {"event_type", "user_id", "booking_id", "payout_id", "case_id", "message_id"}
MAX_ATTEMPTS = 10


class PermanentDeliveryError(Exception):
    """A retry cannot fix an invalid payload or rejected recipient."""


@dataclass(frozen=True)
class DeliveryRequest:
    id: str
    user_id: str
    channel: str
    subject: str
    body: str


@dataclass(frozen=True)
class DeliveryReceipt:
    reference: str
    simulated: bool = False
    accepted: bool = False


class NotificationGateway(Protocol):
    def send(self, request: DeliveryRequest) -> DeliveryReceipt: ...


class LocalNotificationGateway:
    def send(self, request: DeliveryRequest) -> DeliveryReceipt:
        # Explicit vendor mock: never represent a local receipt as a real email/SMS/push send.
        return DeliveryReceipt("local:" + request.id, simulated=True)


class RelayNotificationGateway:
    def send(self, request: DeliveryRequest) -> DeliveryReceipt:
        from dataclasses import asdict

        settings = get_settings()
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                settings.notification_relay_url,
                headers={
                    "Authorization": "Bearer " + settings.notification_relay_token,
                    "Idempotency-Key": request.id,
                },
                json=asdict(request),
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise TimeoutError("Notification relay temporarily unavailable")
        if response.status_code not in {200, 201, 202}:
            raise PermanentDeliveryError("Notification relay rejected delivery")
        reference = response.json().get("reference")
        if not isinstance(reference, str) or not 1 <= len(reference) <= 200:
            raise PermanentDeliveryError("Invalid notification receipt")
        return DeliveryReceipt(reference, accepted=True)


def validate_template(value: str) -> None:
    template = Template(value)
    if not template.is_valid() or not set(template.get_identifiers()).issubset(VARIABLES):
        raise ValueError("Unsupported template variable or syntax")


def enqueue_once() -> int:
    with SessionLocal.begin() as db:
        notices = db.scalars(
            select(Notification)
            .where(Notification.external_enqueued_at.is_(None))
            .order_by(Notification.created_at, Notification.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        for notice in notices:
            preference = db.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == notice.user_id
                )
            )
            channels = preference.channels if preference else {}
            templates = db.scalars(
                select(NotificationTemplate).where(
                    NotificationTemplate.event_type == notice.kind,
                    NotificationTemplate.enabled.is_(True),
                )
            ).all()
            for template in templates:
                if not channels.get(template.channel, False):
                    continue
                context = {"event_type": notice.kind, "user_id": str(notice.user_id)}
                context.update(
                    {
                        k: str(v)
                        for k, v in notice.payload.items()
                        if k in VARIABLES and v is not None
                    }
                )
                error = None
                subject, body = "", ""
                try:
                    subject = Template(template.subject).substitute(context)
                    body = Template(template.body).substitute(context)
                    if len(subject) > 500 or len(body) > 8000:
                        raise ValueError("Rendered notification exceeds limits")
                except (KeyError, ValueError):
                    error = "TemplateRenderError"
                    subject, body = "", ""
                db.add(
                    NotificationDelivery(
                        notification_id=notice.id,
                        user_id=notice.user_id,
                        channel=template.channel,
                        template_version=template.version,
                        subject=subject,
                        body=body,
                        status="DEAD_LETTER" if error else "PENDING",
                        last_error=error,
                    )
                )
            notice.external_enqueued_at = now()
        return len(notices)


def deliver_once(gateway: NotificationGateway | None = None) -> bool:
    settings = get_settings()
    if gateway is None:
        if settings.notification_mode == "disabled":
            return False  # Durable work waits for explicit configuration; never silently succeeds.
        gateway = (
            LocalNotificationGateway()
            if settings.notification_mode == "local"
            else RelayNotificationGateway()
        )
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(["PENDING", "LEASED"]),
                NotificationDelivery.available_at <= now(),
            )
            .order_by(NotificationDelivery.available_at, NotificationDelivery.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        user = db.get(User, row.user_id)
        preference = db.scalar(
            select(NotificationPreference).where(NotificationPreference.user_id == row.user_id)
        )
        if (
            not user
            or not user.active
            or not preference
            or not preference.channels.get(row.channel)
        ):
            row.status = "CANCELLED"
            row.lease_token = None
            return False
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "DEAD_LETTER"
            row.last_error = "LeaseAttemptsExhausted"
            row.lease_token = None
            return False
        row.status = "LEASED"
        row.attempts += 1
        row.lease_token = str(uuid4())
        row.available_at = now() + timedelta(minutes=2)
        token = row.lease_token
        request = DeliveryRequest(str(row.id), str(row.user_id), row.channel, row.subject, row.body)
        identity = row.id
    receipt, error, permanent = None, None, False
    try:
        receipt = gateway.send(request)
    except Exception as exc:
        error = type(exc).__name__[
            :120
        ]  # Never persist vendor bodies, credentials or recipient PII.
        permanent = isinstance(exc, PermanentDeliveryError)
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == identity)
            .with_for_update()
        )
        if row is None or row.lease_token != token:
            return False
        row.last_error = error
        row.lease_token = None
        if receipt is not None:
            row.status = (
                "SIMULATED"
                if receipt.simulated
                else "ACCEPTED"
                if receipt.accepted
                else "DELIVERED"
            )
            row.provider_reference = receipt.reference
        else:
            row.status = "DEAD_LETTER" if permanent or row.attempts >= MAX_ATTEMPTS else "PENDING"
            row.available_at = now() + timedelta(seconds=min(3600, 2**row.attempts))
    return receipt is not None


def main():
    import logging
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
            enqueue_once()
            deliver_once()
        except Exception:
            logging.getLogger(__name__).error(
                "Notification worker unavailable; durable work retained"
            )
        time.sleep(1)


if __name__ == "__main__":
    main()
