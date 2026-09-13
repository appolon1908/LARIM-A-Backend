from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_marketplace_e2e import login

from larimia.main import app
from larimia.marketplace.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
    User,
    now,
)
from larimia.marketplace.notification_delivery import (
    DeliveryReceipt,
    LocalNotificationGateway,
    PermanentDeliveryError,
    deliver_once,
    enqueue_once,
    validate_template,
)
from larimia.shared.db import SessionLocal
from larimia.shared.events import OutboxEvent

client = TestClient(app)


def scenario():
    with SessionLocal.begin() as db:
        user = User(subject=str(uuid4()), email=str(uuid4()) + "@example.test", roles=["customer"])
        db.add(user)
        db.flush()
        kind = "Test" + uuid4().hex
        event = OutboxEvent(
            aggregate_type="test",
            aggregate_id=str(user.id),
            event_type=kind,
            payload={"user_id": str(user.id), "booking_id": str(uuid4())},
        )
        db.add(event)
        db.flush()
        notice = Notification(event_id=event.id, user_id=user.id, kind=kind, payload=event.payload)
        db.add(notice)
        db.add(NotificationPreference(user_id=user.id, channels={"email": True}))
        db.add(
            NotificationTemplate(
                event_type=kind,
                channel="email",
                subject="Booking $booking_id",
                body="Event $event_type",
            )
        )
        db.flush()
        identity, user_id = notice.id, user.id
    # Existing test notices must not starve the isolated scenario.
    for _ in range(100):
        enqueue_once()
        with SessionLocal() as db:
            row = db.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == identity)
            )
            if row:
                return row.id, user_id, kind
    raise AssertionError("Fanout did not process fixture")


def prioritize(identity):
    with SessionLocal.begin() as db:
        row = db.get(NotificationDelivery, identity)
        row.available_at = now() - timedelta(days=3650)


def test_template_language_is_bounded():
    validate_template("Booking ${booking_id}: $$10")
    for value in ["$password", "${user.__class__}", "$", "${booking_id[0]}"]:
        with pytest.raises(ValueError):
            validate_template(value)


def test_fanout_dedup_snapshot_and_simulated_delivery():
    identity, _, kind = scenario()
    with SessionLocal.begin() as db:
        template = db.scalar(
            select(NotificationTemplate).where(NotificationTemplate.event_type == kind)
        )
        template.body = "Changed"
        template.version += 1
    enqueue_once()
    prioritize(identity)
    assert deliver_once(LocalNotificationGateway())
    with SessionLocal() as db:
        row = db.get(NotificationDelivery, identity)
        assert row.status == "SIMULATED" and row.attempts == 1
        assert row.body == "Event " + kind and row.template_version == 1
        rows = db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == row.notification_id
            )
        ).all()
        assert len(rows) == 1


def test_retry_is_durable_bounded_and_uses_stable_delivery_id():
    identity, _, _ = scenario()
    sent = []

    class Failing:
        def send(self, request):
            sent.append(request.id)
            raise TimeoutError("Sensitive vendor response must not be stored")

    for _ in range(10):
        prioritize(identity)
        assert not deliver_once(Failing())
    with SessionLocal() as db:
        row = db.get(NotificationDelivery, identity)
        assert row.status == "DEAD_LETTER" and row.attempts == 10
        assert row.last_error == "TimeoutError"
    assert sent == [str(identity)] * 10


def test_optout_cancels_queued_delivery():
    identity, user_id, _ = scenario()
    with SessionLocal.begin() as db:
        preference = db.scalar(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        preference.channels = {"email": False}
    prioritize(identity)

    class NeverSend:
        def send(self, request):
            raise AssertionError("Opted-out recipient reached vendor")

    assert not deliver_once(NeverSend())
    with SessionLocal() as db:
        assert db.get(NotificationDelivery, identity).status == "CANCELLED"


def test_recovered_lease_and_network_call_without_row_lock():
    identity, _, _ = scenario()
    with SessionLocal.begin() as db:
        row = db.get(NotificationDelivery, identity)
        row.status, row.lease_token, row.attempts = "LEASED", str(uuid4()), 1
    prioritize(identity)

    class Gateway:
        def send(self, request):
            with SessionLocal.begin() as db:
                # NOWAIT would fail if vendor I/O retained the claim transaction.
                row = db.scalar(
                    select(NotificationDelivery)
                    .where(NotificationDelivery.id == identity)
                    .with_for_update(nowait=True)
                )
                assert row.status == "LEASED" and row.attempts == 2
            return DeliveryReceipt("vendor:" + request.id)

    assert deliver_once(Gateway())
    with SessionLocal() as db:
        assert db.get(NotificationDelivery, identity).status == "DELIVERED"


def test_permissions_preferences_and_dead_letter_replay():
    customer, admin = login("customer1"), login("admin")
    payload = {"subject": "Hello $user_id", "body": "Event $event_type"}
    path = "/api/v1/admin/notifications/templates/CustomerRegistered/email"
    assert (
        client.put(
            path,
            json=payload,
            headers={"Authorization": customer["Authorization"], "Idempotency-Key": str(uuid4())},
        ).status_code
        == 403
    )
    assert (
        client.put(
            path,
            json=payload,
            headers={"Authorization": admin["Authorization"], "Idempotency-Key": str(uuid4())},
        ).status_code
        == 200
    )
    own = "/api/v1/me/notification-preferences"
    headers = {"Authorization": customer["Authorization"], "Idempotency-Key": str(uuid4())}
    body = {"email": True, "sms": False, "push": False}
    assert client.put(own, json=body, headers=headers).json() == body
    assert client.put(own, json=body, headers=headers).json() == body
    assert (
        client.put(own, json={**body, "user_id": str(uuid4())}, headers=headers).status_code == 422
    )
    identity, _, _ = scenario()
    prioritize(identity)

    class Rejected:
        def send(self, request):
            raise PermanentDeliveryError("Invalid destination")

    assert not deliver_once(Rejected())
    path = f"/api/v1/admin/notifications/deliveries/{identity}/replay"
    headers = {"Authorization": admin["Authorization"], "Idempotency-Key": str(uuid4())}
    assert client.post(path, headers=headers).status_code == 200
    assert client.post(path, headers=headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(NotificationDelivery, identity).status == "PENDING"
    visible = client.get(
        "/api/v1/me/notification-deliveries", headers={"Authorization": customer["Authorization"]}
    ).json()["items"]
    assert str(identity) not in {item["id"] for item in visible}
    prioritize(identity)
    assert deliver_once(LocalNotificationGateway())


def test_relay_contract_acceptance_and_error_classification(monkeypatch):
    import httpx

    from larimia.config import get_settings
    from larimia.marketplace.notification_delivery import DeliveryRequest, RelayNotificationGateway

    settings = get_settings()
    monkeypatch.setattr(settings, "notification_relay_url", "https://relay.example.test/send")
    monkeypatch.setattr(settings, "notification_relay_token", "isolated-relay-test")
    request = DeliveryRequest(str(uuid4()), str(uuid4()), "sms", "Title", "Body")
    status = 202
    real_client = httpx.Client

    def handler(incoming):
        assert incoming.headers["Idempotency-Key"] == request.id
        assert incoming.headers["Authorization"] == "Bearer isolated-relay-test"
        return httpx.Response(status, json={"reference": "vendor-reference"})

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    receipt = RelayNotificationGateway().send(request)
    assert receipt.accepted and not receipt.simulated
    status = 429
    with pytest.raises(TimeoutError):
        RelayNotificationGateway().send(request)
    status = 400
    with pytest.raises(PermanentDeliveryError):
        RelayNotificationGateway().send(request)


def test_missing_template_variable_dead_letters_without_losing_in_app_notice():
    identity, _, kind = scenario()
    with SessionLocal.begin() as db:
        row = db.get(NotificationDelivery, identity)
        notice = db.get(Notification, row.notification_id)
        event = OutboxEvent(
            aggregate_type="test",
            aggregate_id=str(notice.user_id),
            event_type=kind,
            payload={"user_id": str(notice.user_id)},
        )
        db.add(event)
        db.flush()
        second = Notification(
            event_id=event.id, user_id=notice.user_id, kind=kind, payload=event.payload
        )
        db.add(second)
        db.flush()
        second_id = second.id
    enqueue_once()
    with SessionLocal() as db:
        notice = db.get(Notification, second_id)
        failed = db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == second_id)
        )
        assert notice.status == "DELIVERED"
        assert failed.status == "DEAD_LETTER" and failed.last_error == "TemplateRenderError"
    prioritize(identity)
    assert deliver_once(LocalNotificationGateway())


def test_notification_worker_bootstraps_without_importing_api():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from larimia.marketplace.notification_delivery import enqueue_once; enqueue_once()",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
