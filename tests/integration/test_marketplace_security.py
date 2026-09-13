import hashlib
import hmac
import json
import time
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_marketplace_e2e import login, post, prepare

from larimia.config import get_settings
from larimia.main import app
from larimia.marketplace.models import Offer, Provider, now
from larimia.shared.db import SessionLocal

client = TestClient(app)


def test_customer_cannot_choose_roles():
    email = str(uuid4()) + "@example.test"
    result = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "isolated-test-password", "roles": ["platform_admin"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == 422
    assert (
        client.get(
            "/api/v1/admin/payments",
            headers={"X-Demo-Subject": "admin", "X-Demo-Roles": "platform_admin"},
        ).status_code
        == 401
    )


def test_refresh_rotation_and_reuse_rejected():
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "customer1@demo.larimia.test", "password": get_settings().seed_password},
    )
    raw = response.json()["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert rotated.status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": raw}).status_code == 401


def test_changed_idempotency_payload_conflicts():
    customer = login("customer1")
    key = str(uuid4())
    payload = {"label": "First", "latitude": 18.4, "longitude": -69.9}
    post("/me/addresses", customer, payload, key=key, expected=201)
    post("/me/addresses", customer, {**payload, "label": "Second"}, key=key, expected=409)


def test_expired_or_suspended_provider_cannot_accept():
    customer, _, _, booking = prepare()
    post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    dispatched = post("/bookings/" + booking["id"] + "/dispatch", customer)
    with SessionLocal.begin() as db:
        offer = db.scalar(select(Offer).where(Offer.booking_id == UUID(booking["id"])))
        provider = db.get(Provider, offer.provider_id)
        from larimia.marketplace.models import User

        username = db.get(User, provider.user_id).email.split("@")[0]
        offer_id = str(offer.id)
        offer.expires_at = now() - timedelta(seconds=1)
    identity = login(username)
    post(
        "/provider/offers/" + offer_id + "/accept",
        identity,
        {"booking_version": dispatched["version"]},
        expected=409,
    )
    with SessionLocal.begin() as db:
        offer = db.get(Offer, UUID(offer_id))
        offer.expires_at = now() + timedelta(minutes=1)
        provider = db.get(Provider, offer.provider_id)
        provider.status = "SUSPENDED"
    post(
        "/provider/offers/" + offer_id + "/accept",
        identity,
        {"booking_version": dispatched["version"]},
        expected=409,
    )
    with SessionLocal.begin() as db:
        db.get(Provider, provider.id).status = "APPROVED"


def test_signed_webhook_deduplicates_and_rejects_tampering(monkeypatch):
    secret = "isolated-webhook-test-secret"
    monkeypatch.setattr(get_settings(), "payment_webhook_secret", secret)
    customer, _, _, booking = prepare()
    payment = post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    raw = json.dumps({"id": str(uuid4()), "payment_id": payment["id"]}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": signature,
        "Content-Type": "application/json",
    }
    first = client.post("/api/v1/webhooks/payments", content=raw, headers=headers)
    assert first.status_code == 202, first.text
    assert (
        client.post("/api/v1/webhooks/payments", content=raw, headers=headers).json()
        == first.json()
    )
    assert (
        client.post("/api/v1/webhooks/payments", content=raw + b" ", headers=headers).status_code
        == 401
    )


def test_database_rejects_unbalanced_journal_and_audit_mutation():
    from larimia.ledger.infrastructure_models import LedgerAccount, LedgerEntry, LedgerTransaction

    with SessionLocal() as db:
        account = db.scalar(select(LedgerAccount))
        assert account is not None
        tx = LedgerTransaction(
            reference_type="test-invalid", reference_id=str(uuid4()), description="rollback fixture"
        )
        db.add(tx)
        db.flush()
        db.add(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=account.id,
                direction="DEBIT",
                amount_minor=100,
                currency=account.currency,
            )
        )
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(
                text(
                    "UPDATE audit_events SET action='changed' "
                    "WHERE id=(SELECT id FROM audit_events LIMIT 1)"
                )
            )
        db.rollback()


def test_upload_privacy_and_type_validation():
    import base64

    provider = login("provider1")
    other = login("provider2")
    result = post(
        "/provider/documents",
        provider,
        {
            "filename": "proof.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"%PDF-1.7\nsynthetic").decode(),
        },
        expected=201,
    )
    assert "storage_key" not in result
    assert (
        client.get(
            "/api/v1/provider/documents/" + result["id"] + "/download", headers=other
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/provider/documents/" + result["id"] + "/download", headers=provider
        ).status_code
        == 200
    )
    post(
        "/provider/documents",
        provider,
        {
            "filename": "payload.html",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"<script>test</script>").decode(),
        },
        expected=422,
    )


def test_request_size_limit():
    response = client.post("/api/v1/auth/login", content=b"x" * 1048577)
    assert response.status_code == 413


def test_outbox_retry_and_no_duplicate_notifications(monkeypatch):
    from larimia.marketplace.models import Notification, User
    from larimia.marketplace.worker import once
    from larimia.shared.events import OutboxEvent

    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == "customer1@demo.larimia.test"))
        event = OutboxEvent(
            aggregate_type="test",
            aggregate_id=str(uuid4()),
            event_type="RetryTest",
            payload={"user_id": str(user.id)},
        )
        db.add(event)
        db.flush()
        event_id = event.id
    import larimia.marketplace.worker as worker

    original = worker.SessionLocal

    class Failing:
        def begin(self):
            raise RuntimeError("temporary dependency outage")

    monkeypatch.setattr(worker, "SessionLocal", Failing())
    with pytest.raises(RuntimeError):
        once()
    monkeypatch.setattr(worker, "SessionLocal", original)
    once()
    once()
    with SessionLocal() as db:
        assert (
            len(db.scalars(select(Notification).where(Notification.event_id == event_id)).all())
            == 1
        )
        assert db.get(OutboxEvent, event_id).published_at is not None


def test_offer_recovery_expands_then_exhausts():
    from larimia.marketplace.dispatch_worker import recover
    from larimia.marketplace.models import DispatchSession
    from larimia.marketplace.models import MarketplaceBooking as Booking

    customer, _, _, booking = prepare()
    post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    post("/bookings/" + booking["id"] + "/dispatch", customer)
    for _attempt in range(3):
        with SessionLocal.begin() as db:
            for offer in db.scalars(
                select(Offer).where(
                    Offer.booking_id == UUID(booking["id"]), Offer.status == "PENDING"
                )
            ):
                offer.expires_at = now() - timedelta(seconds=1)
        recover()
    with SessionLocal() as db:
        assert db.get(Booking, UUID(booking["id"])).status == "NO_PROVIDER_FOUND"
        session = db.scalar(
            select(DispatchSession).where(DispatchSession.booking_id == UUID(booking["id"]))
        )
        assert session.status == "EXHAUSTED"


def test_leased_event_delivery_retries_without_duplicate_domain_effects():
    from larimia.marketplace.event_transport import publish_once
    from larimia.marketplace.models import EventDelivery, User
    from larimia.shared.events import OutboxEvent

    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == "customer1@demo.larimia.test"))
        event = OutboxEvent(
            aggregate_type="test",
            aggregate_id=str(uuid4()),
            event_type="VendorRetry",
            payload={"user_id": str(user.id)},
        )
        db.add(event)
        db.flush()
        delivery = EventDelivery(event_id=event.id)
        db.add(delivery)
        db.flush()
        delivery_id = delivery.id

    class Failure:
        def publish(self, *args):
            raise TimeoutError("unavailable vendor")

    class Success:
        def publish(self, *args):
            return None

    assert publish_once(Failure()) is False
    with SessionLocal.begin() as db:
        row = db.get(EventDelivery, delivery_id)
        assert row.status == "PENDING" and row.attempts == 1
        row.available_at = now() - timedelta(seconds=1)
    assert publish_once(Success()) is True
    with SessionLocal() as db:
        row = db.get(EventDelivery, delivery_id)
        assert row.status == "DELIVERED" and row.attempts == 2


def test_pricing_edit_does_not_reprice_accepted_booking():
    customer, _, _, booking = prepare()
    admin = login("admin")
    service = next(
        row
        for row in client.get("/api/v1/catalog").json()["services"]
        if row["code"] == "MASSAGE_60"
    )
    previous = {key: service[key] for key in ["base_minor", "travel_minor", "tax_bps", "fee_bps"]}
    try:
        response = client.put(
            "/api/v1/admin/pricing/" + service["id"],
            headers={**admin, "Idempotency-Key": str(uuid4())},
            json={**previous, "base_minor": previous["base_minor"] + 50000},
        )
        assert response.status_code == 200
        current = client.get("/api/v1/bookings/" + booking["id"], headers=customer).json()
        assert current["snapshot"] == booking["snapshot"]
    finally:
        client.put(
            "/api/v1/admin/pricing/" + service["id"],
            headers={**admin, "Idempotency-Key": str(uuid4())},
            json=previous,
        )


def test_provider_onboarding_approval_gate():
    email = str(uuid4()) + "@applicant.test"
    credentials = {"email": email, "password": "isolated-applicant-passphrase"}
    assert (
        client.post(
            "/api/v1/auth/register", json=credentials, headers={"Idempotency-Key": str(uuid4())}
        ).status_code
        == 201
    )
    token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
    identity = {"Authorization": "Bearer " + token}
    application = post(
        "/provider/application",
        identity,
        {"services": ["MASSAGE_60"], "skills": ["MASSAGE_60"]},
        expected=201,
    )
    response = client.put(
        "/api/v1/provider/status",
        headers={**identity, "Idempotency-Key": str(uuid4())},
        json={"online": True},
    )
    assert response.status_code == 409
    admin = login("admin")
    for status in ["UNDER_REVIEW", "APPROVED"]:
        post(
            "/admin/providers/" + application["id"] + "/status",
            admin,
            {"status": status, "reason": "Synthetic approval test"},
        )
    response = client.put(
        "/api/v1/provider/status",
        headers={**identity, "Idempotency-Key": str(uuid4())},
        json={"online": True},
    )
    assert response.status_code == 200


def test_support_and_safety_permission_separation():
    customer = login("customer1")
    support = login("support")
    finance = login("finance")
    case = post("/support", customer, {"body": "Synthetic support request"}, expected=201)
    post(
        "/admin/support/" + case["id"] + "/resolve",
        finance,
        {"resolution": "Not authorized"},
        expected=403,
    )
    resolved = post(
        "/admin/support/" + case["id"] + "/resolve",
        support,
        {"resolution": "Synthetic case resolved"},
    )
    assert resolved["status"] == "RESOLVED"
    assert client.get("/api/v1/admin/safety", headers=support).status_code == 403


def test_payout_reservation_is_idempotent_and_balanced():
    finance = login("finance")
    customer, _, _, booking = prepare()
    post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    dispatched = post("/bookings/" + booking["id"] + "/dispatch", customer)
    with SessionLocal() as db:
        from larimia.marketplace.models import User

        offer = db.scalar(select(Offer).where(Offer.booking_id == UUID(booking["id"])))
        provider = db.get(Provider, offer.provider_id)
        provider_name = db.get(User, provider.user_id).email.split("@")[0]
        offer_id = str(offer.id)
        provider_id = str(provider.id)
    identity = login(provider_name)
    post(
        "/provider/offers/" + offer_id + "/accept",
        identity,
        {"booking_version": dispatched["version"]},
    )
    for action in ["en-route", "arrive", "start", "complete"]:
        post("/provider/jobs/" + booking["id"] + "/" + action, identity)
    payload = {"provider_id": provider_id, "currency": "DOP"}
    key = str(uuid4())
    payout = post("/admin/payouts", finance, payload, key=key, expected=201)
    assert post("/admin/payouts", finance, payload, key=key, expected=201) == payout
    complete = post("/admin/payouts/" + payout["id"] + "/complete", finance)
    assert complete["status"] == "COMPLETED"
    assert (
        client.get("/api/v1/finance/reconciliation-breaks", headers=finance).json()["items"] == []
    )
