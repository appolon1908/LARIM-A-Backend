import asyncio
import hashlib
import json
import re
import secrets
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select

from larimia.bookings.infrastructure.models import Booking
from larimia.config import get_settings
from larimia.marketplace.models import Assignment, Customer, Provider
from larimia.shared.auth import Principal, Role, get_principal
from larimia.shared.db import SessionLocal
from larimia.workers.outbox import stream_key


router = APIRouter()
CURSOR_PATTERN = re.compile(r"^(?:\$|\d+-\d+)$")


class TicketRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=255)


def _safe_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def authorized(principal: Principal, topic: str) -> bool:
    with SessionLocal() as db:
        if topic.startswith("booking:"):
            booking_id = _safe_uuid(topic.split(":", 1)[1])
            if booking_id is None:
                return False
            booking = db.get(Booking, booking_id)
            if booking is None:
                return False
            if principal.roles.intersection(
                {Role.DISPATCHER, Role.SUPPORT, Role.SAFETY, Role.PLATFORM_ADMIN}
            ):
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

        if topic.startswith("provider:") and topic.endswith(":offers"):
            parts = topic.split(":")
            if len(parts) != 3:
                return False
            provider_id = _safe_uuid(parts[1])
            if provider_id is None:
                return False
            provider = db.get(Provider, provider_id)
            return bool(
                Role.PROVIDER in principal.roles
                and provider
                and provider.identity_issuer == principal.issuer
                and provider.identity_subject == principal.subject
            )

        return topic == "ops:dispatch" and bool(
            principal.roles.intersection(
                {Role.DISPATCHER, Role.SUPPORT, Role.SAFETY, Role.PLATFORM_ADMIN}
            )
        )


def _ticket_key(ticket: str) -> str:
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    return f"ws-ticket:{digest}"


def _principal_payload(principal: Principal, topic: str) -> str:
    return json.dumps(
        {
            "subject": principal.subject,
            "issuer": principal.issuer,
            "roles": sorted(role.value for role in principal.roles),
            "organization_id": principal.organization_id,
            "market_codes": sorted(principal.market_codes),
            "topic": topic,
        },
        separators=(",", ":"),
    )


def _principal_from_payload(raw: str) -> tuple[Principal, str]:
    value = json.loads(raw)
    valid_roles = {item.value for item in Role}
    roles = frozenset(
        Role(role)
        for role in value.get("roles", [])
        if role in valid_roles
    )
    principal = Principal(
        subject=str(value["subject"]),
        issuer=str(value["issuer"]),
        roles=roles,
        organization_id=value.get("organization_id"),
        market_codes=frozenset(
            str(item) for item in value.get("market_codes", [])
        ),
    )
    return principal, str(value["topic"])


@router.post("/tickets", status_code=201)
async def create_ticket(
    payload: TicketRequest,
    principal: Principal = Depends(get_principal),
):
    if not authorized(principal, payload.topic):
        raise HTTPException(403, detail={"code": "REALTIME_TOPIC_FORBIDDEN"})

    settings = get_settings()
    if not settings.websocket_redis_url:
        raise HTTPException(503, detail={"code": "REALTIME_UNAVAILABLE"})

    ticket = secrets.token_urlsafe(32)
    client = redis.from_url(
        settings.websocket_redis_url,
        decode_responses=True,
    )
    try:
        created = await client.set(
            _ticket_key(ticket),
            _principal_payload(principal, payload.topic),
            ex=settings.websocket_ticket_ttl_seconds,
            nx=True,
        )
    finally:
        await client.aclose()
    if not created:
        raise HTTPException(503, detail={"code": "REALTIME_TICKET_FAILED"})
    return {
        "ticket": ticket,
        "expires_in": settings.websocket_ticket_ttl_seconds,
    }


async def _consume_ticket(
    client: redis.Redis,
    ticket: str,
) -> tuple[Principal, str] | None:
    raw = await client.getdel(_ticket_key(ticket))
    if not raw:
        return None
    try:
        return _principal_from_payload(raw)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def stream(ws: WebSocket, expected_topic: str):
    ticket = ws.query_params.get("ticket")
    if not ticket:
        await ws.close(code=4401)
        return

    settings = get_settings()
    if not settings.websocket_redis_url:
        await ws.close(code=1013)
        return
    client = redis.from_url(
        settings.websocket_redis_url,
        decode_responses=True,
    )
    ticket_data = await _consume_ticket(client, ticket)
    if ticket_data is None:
        await client.aclose()
        await ws.close(code=4401)
        return

    principal, granted_topic = ticket_data
    if granted_topic != expected_topic or not authorized(principal, expected_topic):
        await client.aclose()
        await ws.close(code=4403)
        return

    last_event_id = ws.query_params.get("last_event_id", "$")
    if not CURSOR_PATTERN.fullmatch(last_event_id):
        await client.aclose()
        await ws.close(code=4400)
        return

    key = stream_key(expected_topic)
    if last_event_id == "$":
        latest = await client.xrevrange(key, count=1)
        cursor = latest[0][0] if latest else "0-0"
    else:
        cursor = last_event_id

    await ws.accept()
    try:
        while True:
            rows = await client.xread(
                {key: cursor},
                count=100,
                block=20_000,
            )
            if not rows:
                await asyncio.wait_for(
                    ws.send_json(
                        {
                            "type": "system.heartbeat",
                            "cursor": cursor,
                        }
                    ),
                    timeout=5,
                )
                continue

            for _, messages in rows:
                for message_id, fields in messages:
                    cursor = message_id
                    try:
                        event = json.loads(fields["event"])
                    except (KeyError, TypeError, json.JSONDecodeError):
                        event = {
                            "type": "system.invalid_event",
                            "data": {},
                        }
                    event["cursor"] = cursor
                    await asyncio.wait_for(
                        ws.send_json(event),
                        timeout=5,
                    )
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
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
