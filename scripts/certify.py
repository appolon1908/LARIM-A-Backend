"""Execute the marketplace scenario over HTTP against an explicitly supplied local URL."""

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from websockets.sync.client import connect

from larimia.config import get_settings


def certify(base: str, allow_staging: bool = False) -> dict:
    settings = get_settings()
    if not allow_staging and (settings.env != "development" or settings.auth_mode != "local"):
        raise RuntimeError("This script is for isolated local mock-payment certification only")
    tokens_by_name = {}
    if allow_staging:
        if not settings.certification_enabled or not base.startswith("https://"):
            raise RuntimeError("Staging certification requires explicit enablement and HTTPS")
        tokens_by_name = json.loads(settings.certification_tokens_json)
        required = {"customer1", "admin", "provider1", "provider2", "provider3", "provider4"}
        if not isinstance(tokens_by_name, dict) or not required.issubset(tokens_by_name):
            raise RuntimeError("Dedicated staging identity tokens are required")
    started = datetime.now(UTC)
    results = {}
    client = httpx.Client(base_url=base.rstrip("/"), timeout=10)

    def request(method, path, token=None, body=None):
        headers = {"Idempotency-Key": str(uuid4())}
        if token:
            headers["Authorization"] = "Bearer " + token
        response = client.request(method, path, headers=headers, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
        return response.json() if response.content else None

    def login(name):
        if tokens_by_name:
            return tokens_by_name[name]
        return request(
            "POST",
            "/api/v1/auth/login",
            body={"email": name + "@demo.larimia.test", "password": settings.seed_password},
        )["access_token"]

    results["health"] = request("GET", "/health/live")["status"] == "ok"
    readiness = request("GET", "/health/ready")
    results["readiness"] = readiness["status"] == "ready"
    if readiness.get("payment_mode") != "mock":
        raise RuntimeError("Certification must not transact with a real payment gateway")
    customer, admin = login("customer1"), login("admin")
    results["customer_login"] = True
    services = request("GET", "/api/v1/catalog")["services"]
    results["catalog"] = any(row["code"] == "MASSAGE_60" for row in services)
    address = request("GET", "/api/v1/me/addresses", customer)["items"][0]
    results["service_location"] = True
    tokens = []
    for name in ["provider1", "provider2", "provider3", "provider4"]:
        token = login(name)
        request("PUT", "/api/v1/provider/status", token, {"online": True})
        request(
            "PUT",
            "/api/v1/provider/availability",
            token,
            [{"start": started.isoformat(), "end": (started + timedelta(days=7)).isoformat()}],
        )
        tokens.append(token)
    quote = request(
        "POST",
        "/api/v1/quotes",
        customer,
        {
            "service_code": "MASSAGE_60",
            "address_id": address["id"],
            "scheduled_start": (started + timedelta(days=1)).isoformat(),
        },
    )
    results["quote"] = quote["total_minor"] > 0
    booking = request("POST", "/api/v1/bookings", customer, {"quote_id": quote["id"]})
    identity = booking["id"]
    results["quote_acceptance_and_booking"] = booking["status"] == "QUOTED"
    payment = request(
        "POST",
        "/api/v1/payments/authorize",
        customer,
        {"booking_id": identity, "payment_method_token": "mock_success"},
    )
    results["payment_authorized"] = payment["status"] == "AUTHORIZED"
    booking = request("POST", "/api/v1/bookings/" + identity + "/dispatch", customer)
    results["dispatch"] = booking["status"] == "OFFERED"
    provider = None
    for token in tokens:
        offers = request("GET", "/api/v1/provider/offers", token)["offers"]
        offer = next((row for row in offers if row["booking_id"] == identity), None)
        if offer:
            provider = token
            booking = request(
                "POST",
                "/api/v1/provider/offers/" + offer["id"] + "/accept",
                provider,
                {"booking_version": booking["version"]},
            )
            break
    if not provider:
        raise RuntimeError("No provider received a certification offer")
    results["provider_login_online_offer_acceptance"] = booking["status"] == "ASSIGNED"
    results["customer_sees_assignment"] = (
        request("GET", "/api/v1/bookings/" + identity, customer)["provider_id"] is not None
    )
    request("POST", "/api/v1/provider/jobs/" + identity + "/en-route", provider)
    results["en_route"] = True
    request(
        "PUT", "/api/v1/provider/location", provider, {"latitude": 18.4861, "longitude": -69.9312}
    )
    results["location"] = (
        request("GET", "/api/v1/bookings/" + identity + "/location", customer)["location"]
        is not None
    )
    request("POST", "/api/v1/provider/jobs/" + identity + "/arrive", provider)
    results["arrived"] = True
    request("POST", "/api/v1/provider/jobs/" + identity + "/start", provider)
    results["job_started"] = True
    import base64

    document = request(
        "POST",
        "/api/v1/provider/documents",
        provider,
        {
            "booking_id": identity,
            "filename": "evidence.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"%PDF-1.7\nSynthetic certification only").decode(),
        },
    )
    results["private_evidence_received"] = document["status"] == "QUARANTINED"
    booking = request("POST", "/api/v1/provider/jobs/" + identity + "/complete", provider)
    results["job_completed_and_payment_captured"] = booking["status"] == "PAYMENT_CAPTURED"
    receipt = request("GET", "/api/v1/bookings/" + identity + "/receipt", customer)
    results["customer_receipt"] = receipt["payment"]["status"] == "CAPTURED"
    earnings = request("GET", "/api/v1/provider/earnings", provider)["items"]
    results["provider_earning"] = any(row["booking_id"] == identity for row in earnings)
    request(
        "POST",
        "/api/v1/reviews",
        customer,
        {"booking_id": identity, "rating": 5, "body": "Synthetic certification"},
    )
    results["review"] = True
    results["admin_booking_visibility"] = any(
        row["id"] == identity for row in request("GET", "/api/v1/admin/bookings", admin)["items"]
    )
    results["admin_payment_visibility"] = any(
        row["id"] == payment["id"]
        for row in request("GET", "/api/v1/admin/payments", admin)["items"]
    )
    finance = request("GET", "/api/v1/admin/finance", admin)
    results["admin_ledger_and_earning_visibility"] = bool(finance["entries"]) and any(
        row["booking_id"] == identity for row in finance["earnings"]
    )
    results["balanced_ledger"] = (
        request("GET", "/api/v1/finance/reconciliation-breaks", admin)["items"] == []
    )
    results["audit_trail"] = any(
        row["resource_id"] == identity
        for row in request("GET", "/api/v1/admin/audit", admin)["items"]
    )
    wsbase = base.replace("http://", "ws://").replace("https://", "wss://")
    found = False
    with connect(wsbase + "/api/v1/realtime", open_timeout=5) as websocket:
        websocket.send(json.dumps({"access_token": customer, "since": started.isoformat()}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            event = json.loads(websocket.recv(timeout=5))
            if event.get("data", {}).get("booking_id") == identity:
                found = True
                break
    results["worker_and_realtime_delivery"] = found
    client.close()
    report = {
        "environment": "azure-staging" if allow_staging else "local-container",
        "cloud_staging_certified": allow_staging,
        "base_url": base,
        "started_at": started.isoformat(),
        "booking_id": identity,
        "checks": results,
        "status": "PASS" if all(results.values()) else "FAIL",
    }
    if report["status"] != "PASS":
        raise RuntimeError("Certification failed: " + json.dumps(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", default="/tmp/larimia-certification.json")
    parser.add_argument("--allow-staging", action="store_true")
    args = parser.parse_args()
    report = certify(args.base_url, args.allow_staging)
    from pathlib import Path

    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
