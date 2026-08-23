import asyncio
import json
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from larimia.bookings.infrastructure.models import Booking
from larimia.config import get_settings
from larimia.marketplace.models import Assignment, Customer, Provider
from larimia.shared.auth import Role, _principal_from_token
from larimia.shared.db import SessionLocal

router = APIRouter()


def authorized(principal, topic: str) -> bool:
    with SessionLocal() as db:
        if topic.startswith("booking:"):
            booking = db.get(Booking, uuid.UUID(topic.split(":", 1)[1]))
            if not booking:
                return False
            if principal.roles.intersection({Role.DISPATCHER, Role.SUPPORT, Role.PLATFORM_ADMIN}):
                return (
                    Role.PLATFORM_ADMIN in principal.roles
                    or not principal.market_codes
                    or booking.market_code in principal.market_codes
                )
            customer = db.scalar(
                select(Customer).where(
                    Customer.identity_issuer == principal.issuer,
                    Customer.identity_subject == principal.subject,
                )
            )
            if customer and booking.customer_id == customer.id:
                return True
            provider = db.scalar(
                select(Provider).where(
                    Provider.identity_issuer == principal.issuer,
                    Provider.identity_subject == principal.subject,
                )
            )
            return bool(
                provider
                and db.scalar(
                    select(Assignment.id).where(
                        Assignment.booking_id == booking.id,
                        Assignment.provider_id == provider.id,
                    )
                )
            )
        if topic.startswith("provider:"):
            provider = db.get(Provider, uuid.UUID(topic.split(":")[1]))
            return bool(
                Role.PROVIDER in principal.roles
                and provider
                and provider.identity_issuer == principal.issuer
                and provider.identity_subject == principal.subject
            )
        return topic == "ops:dispatch" and bool(
            principal.roles.intersection({Role.DISPATCHER, Role.SUPPORT, Role.PLATFORM_ADMIN})
        )


async def stream(ws: WebSocket, topic: str):
    token = ws.query_params.get("access_token")
    if not token:
        await ws.close(code=4401)
        return
    try:
        principal = _principal_from_token(token)
    except Exception:
        await ws.close(code=4401)
        return
    if not authorized(principal, topic):
        await ws.close(code=4403)
        return
    url = get_settings().websocket_redis_url
    if not url:
        await ws.close(code=1013)
        return
    client = redis.from_url(url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(topic)
    await ws.accept()
    sequence = 0
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=20)
            if message:
                sequence += 1
                try:
                    event = json.loads(message["data"])
                except Exception:
                    event = {"type": "system.raw", "data": {"payload": message["data"]}}
                event.setdefault("id", str(uuid.uuid4()))
                event.setdefault("version", 1)
                event.setdefault("occurred_at", datetime.now(UTC).isoformat())
                event["sequence"] = sequence
                event.setdefault("aggregate_id", topic.split(":")[-1])
                await asyncio.wait_for(ws.send_json(event), timeout=5)
            else:
                await asyncio.wait_for(
                    ws.send_json({"type": "system.heartbeat", "sequence": sequence}),
                    timeout=5,
                )
    except (TimeoutError, WebSocketDisconnect):
        pass
    finally:
        await pubsub.unsubscribe(topic)
        await pubsub.aclose()
        await client.aclose()


@router.websocket("/bookings/{booking_id}")
async def booking(ws: WebSocket, booking_id: str):
    await stream(ws, f"booking:{booking_id}")


@router.websocket("/providers/{provider_id}/offers")
async def provider(ws: WebSocket, provider_id: str):
    await stream(ws, f"provider:{provider_id}:offers")


@router.websocket("/ops/dispatch")
async def ops(ws: WebSocket):
    await stream(ws, "ops:dispatch")
