"""Runs against an isolated migrated PostgreSQL database, never a production database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from larimia.config import get_settings
from larimia.main import app
from larimia.marketplace.models import Payment, Provider, now
from larimia.marketplace.worker import once
from larimia.shared.db import SessionLocal

client = TestClient(app)


def login(name):
    result = client.post(
        "/api/v1/auth/login",
        json={"email": name + "@demo.larimia.test", "password": get_settings().seed_password},
    )
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def post(path, identity, body=None, key=None, expected=200):
    result = client.post(
        "/api/v1" + path, headers={**identity, "Idempotency-Key": key or str(uuid4())}, json=body
    )
    assert result.status_code == expected, result.text
    return result.json()


def prepare():
    customer = login("customer1")
    provider = login("provider1")
    other_provider = login("provider2")
    with SessionLocal.begin() as db:
        for row in db.scalars(select(Provider)):
            row.online = row.status == "APPROVED"
            row.workload = 0
    address = client.get("/api/v1/me/addresses", headers=customer).json()["items"][0]
    quote = post(
        "/quotes",
        customer,
        {
            "service_code": "MASSAGE_60",
            "address_id": address["id"],
            "scheduled_start": (now() + timedelta(days=1)).isoformat(),
        },
        expected=201,
    )
    key = str(uuid4())
    booking = post("/bookings", customer, {"quote_id": quote["id"]}, key=key, expected=201)
    assert (
        post("/bookings", customer, {"quote_id": quote["id"]}, key=key, expected=201)["id"]
        == booking["id"]
    )
    return customer, provider, other_provider, booking


def test_complete_marketplace_and_idempotent_refund():
    customer, provider, other_provider, booking = prepare()
    other_customer = login("customer2")
    assert (
        client.get("/api/v1/bookings/" + booking["id"], headers=other_customer).status_code == 404
    )
    assert client.get("/api/v1/admin/payments", headers=customer).status_code == 403
    payment = post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    assigned = post("/bookings/" + booking["id"] + "/dispatch", customer)
    offer = None
    for name in ["provider1", "provider2", "provider3", "provider4"]:
        candidate = login(name)
        offers = client.get("/api/v1/provider/offers", headers=candidate).json()["offers"]
        offer = next((row for row in offers if row["booking_id"] == booking["id"]), None)
        if offer:
            provider = candidate
            break
    assert offer is not None
    assigned = post(
        "/provider/offers/" + offer["id"] + "/accept",
        provider,
        {"booking_version": assigned["version"]},
    )
    invalid = client.post(
        "/api/v1/provider/jobs/" + booking["id"] + "/complete",
        headers={**provider, "Idempotency-Key": str(uuid4())},
    )
    assert invalid.status_code == 409
    for action in ["en-route", "arrive", "start", "complete"]:
        key = str(uuid4())
        assigned = post("/provider/jobs/" + booking["id"] + "/" + action, provider, key=key)
        assert post("/provider/jobs/" + booking["id"] + "/" + action, provider, key=key) == assigned
    assert assigned["status"] == "PAYMENT_CAPTURED"
    post("/reviews", customer, {"booking_id": booking["id"], "rating": 5}, expected=201)
    once()
    assert client.get("/api/v1/me/notifications", headers=customer).json()["items"]
    finance = login("finance")
    key = str(uuid4())
    refund = post(
        "/payments/refunds",
        finance,
        {"payment_id": payment["id"], "amount_minor": 1000, "reason": "Service credit"},
        key=key,
        expected=201,
    )
    assert (
        post(
            "/payments/refunds",
            finance,
            {"payment_id": payment["id"], "amount_minor": 1000, "reason": "Service credit"},
            key=key,
            expected=201,
        )
        == refund
    )
    with SessionLocal() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM (SELECT transaction_id FROM ledger_entries "
                    "GROUP BY transaction_id HAVING sum(CASE WHEN direction='DEBIT' "
                    "THEN amount_minor ELSE -amount_minor END) <> 0) invalid"
                )
            )
            == 0
        )
        assert db.get(Payment, payment["id"]).refunded_minor == 1000
    admin = login("admin")
    assert any(
        row["resource_id"] == booking["id"]
        for row in client.get("/api/v1/admin/audit", headers=admin).json()["items"]
    )


def test_two_providers_cannot_win_booking():
    customer, p1, p2, booking = prepare()
    post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    dispatched = post("/bookings/" + booking["id"] + "/dispatch", customer)
    candidates = []
    for name in ["provider1", "provider2", "provider3", "provider4"]:
        identity = login(name)
        offers = client.get("/api/v1/provider/offers", headers=identity).json()["offers"]
        offer = next((row for row in offers if row["booking_id"] == booking["id"]), None)
        if offer:
            candidates.append((identity, offer))
    assert len(candidates) >= 2

    def attempt(pair):
        identity, offer = pair
        with TestClient(app) as local_client:
            return local_client.post(
                "/api/v1/provider/offers/" + offer["id"] + "/accept",
                headers={**identity, "Idempotency-Key": str(uuid4())},
                json={"booking_version": dispatched["version"]},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, candidates[:2]))
    assert sorted(results) == [200, 409]


def test_payment_failure_and_no_provider():
    customer, provider, _, booking = prepare()
    post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_declined"},
        expected=422,
    )
    assert (
        client.get("/api/v1/bookings/" + booking["id"], headers=customer).json()["status"]
        == "QUOTED"
    )
    post(
        "/payments/authorize",
        customer,
        {"booking_id": booking["id"], "payment_method_token": "mock_success"},
        expected=201,
    )
    with SessionLocal.begin() as db:
        for row in db.scalars(select(Provider)):
            row.online = False
    assert (
        post("/bookings/" + booking["id"] + "/dispatch", customer)["status"] == "NO_PROVIDER_FOUND"
    )
