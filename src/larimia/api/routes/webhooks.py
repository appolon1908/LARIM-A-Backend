import hashlib

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()


@router.post("/payments/{provider}")
async def payment_webhook(
    provider: str,
    request: Request,
    x_event_id: str | None = Header(default=None, alias="X-Event-Id"),
):
    body = await request.body()
    if not x_event_id:
        raise HTTPException(status_code=400, detail={"code": "WEBHOOK_EVENT_ID_REQUIRED"})
    # Signature verification must be implemented inside each production provider adapter.
    digest = hashlib.sha256(body).hexdigest()
    return {"accepted": True, "provider": provider, "event_id": x_event_id, "body_sha256": digest}


@router.post("/identity/{provider}")
async def identity_webhook(
    provider: str,
    request: Request,
    x_event_id: str | None = Header(default=None, alias="X-Event-Id"),
):
    if not x_event_id:
        raise HTTPException(status_code=400, detail={"code": "WEBHOOK_EVENT_ID_REQUIRED"})
    await request.body()
    return {"accepted": True, "provider": provider, "event_id": x_event_id}
