import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.shared.db import get_db
from larimia.shared.events import InboxReceipt

router = APIRouter()
ALLOWED = {"payments", "payouts", "identity", "background-checks", "sms", "email", "push"}


def configured():
    try:
        return json.loads(get_settings().webhook_secrets_json)
    except Exception:
        return {}


async def verify(request, family, provider, timestamp, signature, event_id):
    secret = configured().get(f"{family}:{provider}")
    if family not in ALLOWED or not secret:
        raise HTTPException(404, detail={"code": "WEBHOOK_PROVIDER_NOT_CONFIGURED"})
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(415, detail={"code": "CONTENT_TYPE_REQUIRED"})
    body = await request.body()
    if len(body) > get_settings().max_webhook_bytes:
        raise HTTPException(413, detail={"code": "WEBHOOK_TOO_LARGE"})
    if not timestamp or not signature or not event_id:
        raise HTTPException(400, detail={"code": "WEBHOOK_HEADERS_REQUIRED"})
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(400, detail={"code": "INVALID_TIMESTAMP"})
    if abs(int(time.time()) - ts) > 300:
        raise HTTPException(400, detail={"code": "WEBHOOK_REPLAY_WINDOW"})
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.removeprefix("sha256=")):
        raise HTTPException(401, detail={"code": "INVALID_SIGNATURE"})
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, detail={"code": "INVALID_JSON"})


async def ingest(request, family, provider, db, timestamp, signature, event_id):
    payload = await verify(request, family, provider, timestamp, signature, event_id)
    existing = db.scalar(
        select(InboxReceipt).where(
            InboxReceipt.provider == f"{family}:{provider}",
            InboxReceipt.external_event_id == event_id,
        )
    )
    if not existing:
        db.add(
            InboxReceipt(
                provider=f"{family}:{provider}",
                external_event_id=event_id,
                payload={"schema_version": 1, "data": payload},
                received_at=datetime.now(UTC),
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
    return await ingest(request, family, provider, db, timestamp, signature, event_id)


@router.post("/odoo")
async def odoo(
    request: Request,
    timestamp: str | None = Header(default=None, alias="X-Webhook-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    event_id: str | None = Header(default=None, alias="X-Event-Id"),
    db: Session = Depends(get_db),
):
    return await ingest(request, "identity", "odoo", db, timestamp, signature, event_id)
