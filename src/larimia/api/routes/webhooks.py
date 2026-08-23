import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.shared.db import get_db
from larimia.shared.events import InboxReceipt


router = APIRouter()
ALLOWED_FAMILIES = {
    "payments",
    "payouts",
    "identity",
    "background-checks",
    "sms",
    "email",
    "push",
}
WEBHOOK_REPLAY_WINDOW_SECONDS = 300


def _configured_secrets() -> dict[str, str | list[str]]:
    try:
        value = json.loads(get_settings().webhook_secrets_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "WEBHOOK_CONFIGURATION_INVALID"},
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=500,
            detail={"code": "WEBHOOK_CONFIGURATION_INVALID"},
        )
    return value


def _provider_secrets(family: str, provider: str) -> list[str]:
    value = _configured_secrets().get(f"{family}:{provider}")
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _signature_matches(
    *,
    secrets: list[str],
    timestamp: str,
    body: bytes,
    signature: str,
) -> bool:
    supplied = signature.removeprefix("sha256=")
    signed_payload = f"{timestamp}.".encode() + body
    for secret in secrets:
        expected = hmac.new(
            secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, supplied):
            return True
    return False


async def _verify(
    request: Request,
    family: str,
    provider: str,
    timestamp: str | None,
    signature: str | None,
    event_id: str | None,
) -> tuple[dict, str]:
    if family not in ALLOWED_FAMILIES:
        raise HTTPException(404, detail={"code": "WEBHOOK_PROVIDER_NOT_CONFIGURED"})

    secrets = _provider_secrets(family, provider)
    if not secrets:
        raise HTTPException(404, detail={"code": "WEBHOOK_PROVIDER_NOT_CONFIGURED"})

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(415, detail={"code": "CONTENT_TYPE_REQUIRED"})

    body = await request.body()
    if len(body) > get_settings().max_webhook_bytes:
        raise HTTPException(413, detail={"code": "WEBHOOK_TOO_LARGE"})

    if not timestamp or not signature or not event_id:
        raise HTTPException(400, detail={"code": "WEBHOOK_HEADERS_REQUIRED"})
    if len(event_id) > 255:
        raise HTTPException(400, detail={"code": "WEBHOOK_EVENT_ID_INVALID"})

    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "INVALID_TIMESTAMP"}) from exc

    if abs(int(time.time()) - timestamp_value) > WEBHOOK_REPLAY_WINDOW_SECONDS:
        raise HTTPException(400, detail={"code": "WEBHOOK_REPLAY_WINDOW"})

    if not _signature_matches(
        secrets=secrets,
        timestamp=timestamp,
        body=body,
        signature=signature,
    ):
        raise HTTPException(401, detail={"code": "INVALID_SIGNATURE"})

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, detail={"code": "INVALID_JSON"}) from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, detail={"code": "WEBHOOK_PAYLOAD_INVALID"})

    return payload, hashlib.sha256(body).hexdigest()


async def _ingest(
    request: Request,
    family: str,
    provider: str,
    db: Session,
    timestamp: str | None,
    signature: str | None,
    event_id: str | None,
) -> Response:
    payload, body_sha256 = await _verify(
        request,
        family,
        provider,
        timestamp,
        signature,
        event_id,
    )
    provider_key = f"{family}:{provider}"

    db.execute(
        insert(InboxReceipt)
        .values(
            provider=provider_key,
            external_event_id=event_id,
            body_sha256=body_sha256,
            payload={"schema_version": 1, "data": payload},
            status="RECEIVED",
            attempts=0,
            received_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(
            index_elements=["provider", "external_event_id"]
        )
    )
    db.commit()
    return Response(status_code=202)


@router.post("/{family}/{provider}")
async def generic(
    family: str,
    provider: str,
    request: Request,
    timestamp: str | None = Header(default=None, alias="X-Webhook-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    event_id: str | None = Header(default=None, alias="X-Event-Id"),
    db: Session = Depends(get_db),
):
    return await _ingest(
        request,
        family,
        provider,
        db,
        timestamp,
        signature,
        event_id,
    )


@router.post("/odoo")
async def odoo(
    request: Request,
    timestamp: str | None = Header(default=None, alias="X-Webhook-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    event_id: str | None = Header(default=None, alias="X-Event-Id"),
    db: Session = Depends(get_db),
):
    return await _ingest(
        request,
        "identity",
        "odoo",
        db,
        timestamp,
        signature,
        event_id,
    )
