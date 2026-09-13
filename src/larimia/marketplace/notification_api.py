from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from larimia.shared.audit import record_audit
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key

from .models import (
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
    User,
    now,
)
from .notification_delivery import CHANNELS, validate_template
from .routes import run
from .security import current_user, require
from .service import serialize

router = APIRouter(tags=["notifications"])
Channel = Literal["email", "sms", "push"]


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: bool = False
    sms: bool = False
    push: bool = False


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    enabled: bool = True

    @field_validator("subject", "body")
    @classmethod
    def validate_variables(cls, value: str) -> str:
        validate_template(value)
        return value


class TemplateOutput(TemplateInput):
    id: UUID
    created_at: datetime
    event_type: str
    channel: Channel
    version: int


class TemplatePage(BaseModel):
    items: list[TemplateOutput]


class DeliveryOutput(BaseModel):
    id: UUID
    created_at: datetime
    notification_id: UUID
    user_id: UUID
    channel: Channel
    template_version: int
    subject: str
    body: str
    status: Literal[
        "PENDING", "LEASED", "ACCEPTED", "DELIVERED", "SIMULATED", "DEAD_LETTER", "CANCELLED"
    ]
    attempts: int
    available_at: datetime
    last_error: str | None
    provider_reference: str | None


class DeliveryPage(BaseModel):
    items: list[DeliveryOutput]


@router.get("/me/notification-preferences", response_model=PreferencesInput)
def preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id))
    return row.channels if row else PreferencesInput().model_dump()


@router.put("/me/notification-preferences", response_model=PreferencesInput)
def update_preferences(
    payload: PreferencesInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        db.execute(select(User).where(User.id == user.id).with_for_update())
        row = db.scalar(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
        if row is None:
            row = NotificationPreference(user_id=user.id)
            db.add(row)
        row.channels = payload.model_dump()
        record_audit(
            db,
            actor=user.subject,
            action="NotificationPreferencesChanged",
            resource_type="user",
            resource_id=str(user.id),
        )
        return row.channels

    return run(db, user, "notification.preferences", key, payload.model_dump(), action)


@router.put("/admin/notifications/templates/{event_type}/{channel}", response_model=TemplateOutput)
def update_template(
    event_type: str,
    channel: Channel,
    payload: TemplateInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("notification.manage")),
    db: Session = Depends(get_db),
):
    import re

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,119}", event_type):
        raise HTTPException(422, "Invalid event type")

    def action():
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"),
            {"name": "notification-template:" + event_type + ":" + channel},
        )
        row = db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.event_type == event_type,
                NotificationTemplate.channel == channel,
            )
        )
        if row is None:
            row = NotificationTemplate(event_type=event_type, channel=channel, version=1)
            db.add(row)
        else:
            row.version += 1
        row.subject, row.body, row.enabled = payload.subject, payload.body, payload.enabled
        db.flush()
        record_audit(
            db,
            actor=user.subject,
            action="NotificationTemplateChanged",
            resource_type="notification_template",
            resource_id=str(row.id),
        )
        return serialize(row)

    return run(
        db,
        user,
        "notification.template:" + event_type + ":" + channel,
        key,
        payload.model_dump(),
        action,
    )


@router.get("/admin/notifications/templates", response_model=TemplatePage)
def templates(
    user: User = Depends(require("notification.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            serialize(row)
            for row in db.scalars(
                select(NotificationTemplate)
                .order_by(NotificationTemplate.created_at.desc())
                .limit(limit)
            )
        ]
    }


@router.get("/me/notification-deliveries", response_model=DeliveryPage)
def deliveries(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    before: datetime | None = None,
):
    query = select(NotificationDelivery).where(NotificationDelivery.user_id == user.id)
    if before:
        query = query.where(NotificationDelivery.created_at < before)
    return {
        "items": [
            serialize(row)
            for row in db.scalars(
                query.order_by(NotificationDelivery.created_at.desc()).limit(limit)
            )
        ]
    }


@router.get("/admin/notifications/dlq", response_model=DeliveryPage)
def dead_letters(
    user: User = Depends(require("notification.manage")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            serialize(row)
            for row in db.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.status == "DEAD_LETTER")
                .order_by(NotificationDelivery.created_at.desc())
                .limit(limit)
            )
        ]
    }


@router.post("/admin/notifications/deliveries/{delivery_id}/replay", response_model=DeliveryOutput)
def replay(
    delivery_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("notification.manage")),
    db: Session = Depends(get_db),
):
    def action():
        row = db.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == delivery_id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, "Delivery not found")
        if row.status != "DEAD_LETTER" or row.last_error == "TemplateRenderError":
            raise HTTPException(409, "Only rendered dead-letter deliveries can be replayed")
        if row.channel not in CHANNELS:
            raise HTTPException(409, "Unknown delivery channel")
        row.status, row.attempts, row.available_at = "PENDING", 0, now()
        row.last_error, row.lease_token = None, None
        record_audit(
            db,
            actor=user.subject,
            action="NotificationDeliveryReplayed",
            resource_type="notification_delivery",
            resource_id=str(row.id),
        )
        return serialize(row)

    return run(db, user, "notification.replay:" + str(delivery_id), key, {}, action)
