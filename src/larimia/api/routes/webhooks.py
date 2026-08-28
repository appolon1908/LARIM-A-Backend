import hashlib
import hmac
import json
import re
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from larimia.adapters.payment_registry import PaymentConfigurationError, payment_provider
from larimia.config import get_settings
from larimia.payments.errors import PaymentProviderError
from larimia.shared.db import get_db
from larimia.shared.events import InboxReceipt


router = APIRouter()
ALLOWED_FAMILIES = {"payments", "payouts", "identity", "background-checks", "sms", "email", "push"}
PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _configured_secrets() -> dict[str, str | list[str]]:
    value = get_settings().webhook_secret_map
    if not isinstance(value, dict):
        raise HTTPException(500, detail={"code": "WEBHOOK_CONFIGURATION_INVALID"})
    return value


def _provider_secrets(family: str, provider: str) -> list[str]:
    value = _configured_secrets().get(f"{family}:{provider}")
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _signature_matches(*, secrets: list[str], timestamp: str, body: bytes, signature: str) -> bool:
    supplied = signature.removeprefix("sha256=")
    signed_payload = f"{timestamp}.".encode() + body
    return any(hmac.compare_digest(hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest(), supplied) for secret in secrets)


def _validate_body(request: Request, body: bytes) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(415, detail={"code": "CONTENT_TYPE_REQUIRED"})
    if len(body) > get_settings().max_webhook_bytes:
        raise HTTPException(413, detail={"code": "WEBHOOK_TOO_LARGE"})


def _persist(
    db: Session,
    *,
    provider_key: str,
    event_id: str,
    body_sha256: str,
    canonical_payload: dict,
) -> Response:
    if not event_id or len(event_id) > 255:
        raise HTTPException(400, detail={"code": "WEBHOOK_EVENT_ID_INVALID"})
    inserted_id = db.scalar(
        insert(InboxReceipt)
        .values(
            provider=provider_key,
            external_event_id=event_id,
            body_sha256=body_sha256,
            payload={"schema_version": 1, "data": canonical_payload},
            status="RECEIVED",
            attempts=0,
            received_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["provider", "external_event_id"])
        .returning(InboxReceipt.id)
    )
    if inserted_id is None:
        existing = db.scalar(select(InboxReceipt).where(InboxReceipt.provider == provider_key, InboxReceipt.external_event_id == event_id))
        existing_hash = existing.body_sha256 if existing else None
        db.rollback()
        if existing_hash is not None and existing_hash != body_sha256:
            raise HTTPException(409, detail={"code": "WEBHOOK_EVENT_ID_COLLISION"})
        return Response(status_code=200, headers={"X-Webhook-Duplicate": "true"})
    db.commit()
    return Response(status_code=202)


@router.post("/payments/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    _validate_body(request, body)
    try:
        adapter = payment_provider("stripe")
        payload = await adapter.verify_webhook(headers=request.headers, body=body)
        canonical = adapter.translate_webhook(payload)
    except (PaymentProviderError, PaymentConfigurationError) as exc:
        code = exc.code if isinstance(exc, PaymentProviderError) else "WEBHOOK_PROVIDER_NOT_CONFIGURED"
        status = 401 if "SIGNATURE" in code or "REPLAY" in code else 503
        raise HTTPException(status, detail={"code": code}) from exc
    return _persist(db, provider_key="payments:stripe", event_id=str(payload["id"]), body_sha256=hashlib.sha256(body).hexdigest(), canonical_payload=canonical)


@router.post("/payments/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    _validate_body(request, body)
    try:
        adapter = payment_provider("paypal")
        payload = await adapter.verify_webhook(headers=request.headers, body=body)
        canonical = adapter.translate_webhook(payload)
    except (PaymentProviderError, PaymentConfigurationError) as exc:
        code = exc.code if isinstance(exc, PaymentProviderError) else "WEBHOOK_PROVIDER_NOT_CONFIGURED"
        status = 401 if "SIGNATURE" in code else 503
        raise HTTPException(status, detail={"code": code}) from exc
    return _persist(db, provider_key="payments:paypal", event_id=str(payload["id"]), body_sha256=hashlib.sha256(body).hexdigest(), canonical_payload=canonical)


async def _verify_generic(request: Request, family: str, provider: str, timestamp: str | None, signature: str | None, event_id: str | None) -> tuple[dict, str]:
    if family not in ALLOWED_FAMILIES or not PROVIDER_PATTERN.fullmatch(provider):
        raise HTTPException(404, detail={"code": "WEBHOOK_PROVIDER_NOT_CONFIGURED"})
    if family == "payments" and provider in {"stripe", "paypal"}:
        raise HTTPException(404, detail={"code": "NATIVE_WEBHOOK_ENDPOINT_REQUIRED"})
    secrets = _provider_secrets(family, provider)
    if not secrets:
        raise HTTPException(404, detail={"code": "WEBHOOK_PROVIDER_NOT_CONFIGURED"})
    body = await request.body()
    _validate_body(request, body)
    if not timestamp or not signature or not event_id:
        raise HTTPException(400, detail={"code": "WEBHOOK_HEADERS_REQUIRED"})
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "INVALID_TIMESTAMP"}) from exc
    if abs(int(time.time()) - timestamp_value) > get_settings().webhook_replay_window_seconds:
        raise HTTPException(400, detail={"code": "WEBHOOK_REPLAY_WINDOW"})
    if not _signature_matches(secrets=secrets, timestamp=timestamp, body=body, signature=signature):
        raise HTTPException(401, detail={"code": "INVALID_SIGNATURE"})
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, detail={"code": "INVALID_JSON"}) from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, detail={"code": "WEBHOOK_PAYLOAD_INVALID"})
    return payload, hashlib.sha256(body).hexdigest()


@router.post("/{family}/{provider}")
async def generic(family: str, provider: str, request: Request, timestamp: str | None = Header(default=None, alias="X-Webhook-Timestamp"), signature: str | None = Header(default=None, alias="X-Webhook-Signature"), event_id: str | None = Header(default=None, alias="X-Event-Id"), db: Session = Depends(get_db)):
    payload, body_sha256 = await _verify_generic(request, family, provider, timestamp, signature, event_id)
    return _persist(db, provider_key=f"{family}:{provider}", event_id=str(event_id), body_sha256=body_sha256, canonical_payload=payload)


@router.post("/odoo")
async def odoo(request: Request, timestamp: str | None = Header(default=None, alias="X-Webhook-Timestamp"), signature: str | None = Header(default=None, alias="X-Webhook-Signature"), event_id: str | None = Header(default=None, alias="X-Event-Id"), db: Session = Depends(get_db)):
    payload, body_sha256 = await _verify_generic(request, "identity", "odoo", timestamp, signature, event_id)
    return _persist(db, provider_key="identity:odoo", event_id=str(event_id), body_sha256=body_sha256, canonical_payload=payload)
