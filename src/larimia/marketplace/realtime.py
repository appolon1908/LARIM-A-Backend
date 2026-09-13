"""Durable notification stream; reconnect fetches canonical APIs and deduplicates event IDs."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, tuple_

from larimia.shared.auth import get_principal
from larimia.shared.db import SessionLocal

from .models import Notification, User
from .service import serialize

router = APIRouter()
EVENT_NAMES = {
    "ProviderAssigned": "provider.assigned",
    "DispatchOfferCreated": "dispatch.offer.created",
    "ProviderEnRoute": "booking.status.changed",
    "ProviderArrived": "provider.arrived",
    "JobStarted": "job.started",
    "JobCompleted": "job.completed",
    "PaymentCaptured": "payment.completed",
    "ChatMessageCreated": "chat.message.created",
}


def identify(token):
    principal = get_principal(
        authorization="Bearer " + token, x_demo_subject=None, x_demo_roles=None
    )
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                User.subject == principal.subject,
                User.issuer == principal.issuer,
                User.active.is_(True),
            )
        )
        if not user:
            raise ValueError("Account is disabled or missing")
        return user.id


def read_batch(user_id, since, last_id):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.active:
            raise ValueError("Account disabled")
        rows = db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                tuple_(Notification.created_at, Notification.id) > tuple_(since, last_id),
            )
            .order_by(Notification.created_at, Notification.id)
            .limit(100)
        ).all()
        return [serialize(row) for row in rows]


@router.websocket("/realtime")
async def realtime(socket: WebSocket):
    # Send bearer in the first TLS-protected frame, never in logged URLs.
    await socket.accept()
    try:
        hello = await asyncio.wait_for(socket.receive_json(), timeout=10)
        token = hello.get("access_token", "")
        if not isinstance(token, str) or len(token) > 16000:
            raise ValueError("Invalid token")
        user_id = await asyncio.to_thread(identify, token)
        since = datetime.fromisoformat(hello["since"]) if hello.get("since") else datetime.now(UTC)
        if since.tzinfo is None:
            raise ValueError("Timezone required")
        last_id = UUID(hello.get("last_id", "00000000-0000-0000-0000-000000000000"))
        await socket.send_json({"type": "connected", "source_of_truth": "/api/v1/bookings"})
        while True:
            # Revalidate token expiry/account status throughout long-lived connections.
            await asyncio.to_thread(identify, token)
            rows = await asyncio.to_thread(read_batch, user_id, since, last_id)
            for row in rows:
                await socket.send_json(
                    jsonable_encoder(
                        {
                            "type": EVENT_NAMES.get(row["kind"], "booking.status.changed"),
                            "event_type": row["kind"],
                            "id": row["id"],
                            "created_at": row["created_at"],
                            "data": row["payload"],
                        }
                    )
                )
                since, last_id = row["created_at"], row["id"]
            await socket.send_json({"type": "heartbeat"})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception:
        await socket.close(code=1008)
