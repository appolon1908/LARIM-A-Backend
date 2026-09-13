import base64
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_marketplace_e2e import login, post, prepare

from larimia.main import app
from larimia.marketplace.models import Offer, Payment, Provider, Service, User
from larimia.shared.db import SessionLocal

client = TestClient(app)


def test_job_policy_is_immutable_and_completion_requires_cleared_evidence_and_time():
    admin = login("admin")
    with SessionLocal() as db:
        service_id = str(db.scalar(select(Service.id).where(Service.code == "MASSAGE_60")))
    path = f"/api/v1/admin/catalog/{service_id}/job-policy"
    policy = {
        "items": [{"code": "clean_area", "label": "Clean work area", "requires_evidence": True}],
        "require_time_entry": True,
    }
    assert (
        client.put(
            path, json=policy, headers={**admin, "Idempotency-Key": str(uuid4())}
        ).status_code
        == 200
    )
    try:
        customer, _, _, booking = prepare()
    finally:
        assert (
            client.put(
                path,
                json={"items": [], "require_time_entry": False},
                headers={**admin, "Idempotency-Key": str(uuid4())},
            ).status_code
            == 200
        )
    identity = booking["id"]
    post(
        "/payments/authorize",
        customer,
        {"booking_id": identity, "payment_method_token": "mock_success"},
        expected=201,
    )
    offered = post(f"/bookings/{identity}/dispatch", customer)
    with SessionLocal() as db:
        offer = db.scalar(select(Offer).where(Offer.booking_id == UUID(identity)))
        provider = db.get(Provider, offer.provider_id)
        name = db.get(User, provider.user_id).email.split("@")[0]
        offer_id = str(offer.id)
    provider = login(name)
    post(f"/provider/offers/{offer_id}/accept", provider, {"booking_version": offered["version"]})
    for action in ["en-route", "arrive", "start"]:
        post(f"/provider/jobs/{identity}/{action}", provider)
    base = f"/provider/jobs/{identity}"
    checklist = client.get("/api/v1" + base + "/checklist", headers=provider).json()
    assert checklist["items"][0]["code"] == "clean_area"
    assert checklist["require_time_entry"]
    post(base + "/complete", provider, expected=409)
    assert client.get("/api/v1" + base + "/checklist", headers=login("provider5")).status_code in {
        403,
        404,
    }
    evidence = post(
        "/provider/documents",
        provider,
        {
            "filename": "work.pdf",
            "content_type": "application/pdf",
            "booking_id": identity,
            "content_base64": base64.b64encode(b"%PDF-1.4 local evidence fixture").decode(),
        },
        expected=201,
    )
    update = "/api/v1" + base + "/checklist/clean_area"
    assert (
        client.put(
            update,
            json={"completed": True, "evidence_id": evidence["id"]},
            headers={**provider, "Idempotency-Key": str(uuid4())},
        ).status_code
        == 200
    )
    post(base + "/complete", provider, expected=409)
    with SessionLocal() as db:
        assert (
            db.scalar(select(Payment).where(Payment.booking_id == UUID(identity))).status
            == "AUTHORIZED"
        )
    review = f"/admin/jobs/evidence/{evidence['id']}/review"
    post(review, provider, {"decision": "CLEARED", "reason": "Independent review"}, expected=403)
    post(review, admin, {"decision": "CLEARED", "reason": "Reviewed isolated test evidence"})
    post(base + "/complete", provider, expected=409)
    key = str(uuid4())
    first = post(base + "/time/start", provider, key=key)
    assert post(base + "/time/start", provider, key=key)["id"] == first["id"]
    post(base + "/time/start", provider, expected=409)
    post(base + "/complete", provider, expected=409)
    post(base + "/time/stop", provider)
    completed = post(base + "/complete", provider)
    assert completed["status"] == "PAYMENT_CAPTURED"
    post(base + "/time/start", provider, expected=409)
    post(
        review,
        admin,
        {"decision": "REJECTED", "reason": "Cannot revise finalized evidence"},
        expected=409,
    )


def test_job_policy_validation_and_customer_permission():
    customer = login("customer1")
    admin = login("admin")
    with SessionLocal() as db:
        service_id = str(db.scalar(select(Service.id).where(Service.code == "MASSAGE_60")))
    path = f"/api/v1/admin/catalog/{service_id}/job-policy"
    headers = {**customer, "Idempotency-Key": str(uuid4())}
    assert client.put(path, json={"items": []}, headers=headers).status_code == 403
    invalid = {"items": [{"code": "same", "label": "A"}, {"code": "same", "label": "B"}]}
    assert (
        client.put(
            path, json=invalid, headers={**admin, "Idempotency-Key": str(uuid4())}
        ).status_code
        == 422
    )
