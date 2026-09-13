from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from larimia.shared.audit import record_audit
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key

from .models import AccountProfile, Device, RefreshSession, User
from .routes import run
from .security import current_user
from .service import serialize

router = APIRouter(tags=["account"])


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_service_codes: list[str] = Field(default_factory=list, max_length=50)
    accessibility_notes: str = Field(default="", max_length=1000)
    contact_preference: Literal["in_app", "email", "phone"] = "in_app"

    @field_validator("preferred_service_codes")
    @classmethod
    def service_codes(cls, values):
        if any(not 1 <= len(value) <= 80 for value in values) or len(set(values)) != len(values):
            raise ValueError("Service codes must be unique and bounded")
        return values


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(default="", max_length=120)
    locale: str = Field(default="es-DO", pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$")
    timezone: str = Field(default="America/Santo_Domingo", max_length=100)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    platform: Literal["web", "ios", "android"]


class DeviceOutput(DeviceInput):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    revoked: bool


class DevicePage(BaseModel):
    items: list[DeviceOutput]


def profile_for(db: Session, user: User, create=False):
    if create:
        db.execute(select(User).where(User.id == user.id).with_for_update())
    row = db.scalar(select(AccountProfile).where(AccountProfile.user_id == user.id))
    if row is None and create:
        row = AccountProfile(user_id=user.id)
        db.add(row)
        db.flush()
    return row


@router.get("/me/profile", response_model=ProfileInput)
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = profile_for(db, user)
    return (
        {field: getattr(row, field) for field in ProfileInput.model_fields}
        if row
        else ProfileInput().model_dump()
    )


@router.put("/me/profile", response_model=ProfileInput)
def write_profile(
    payload: ProfileInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        row = profile_for(db, user, True)
        row.display_name, row.locale, row.timezone = (
            payload.display_name,
            payload.locale,
            payload.timezone,
        )
        record_audit(
            db,
            actor=user.subject,
            action="AccountProfileUpdated",
            resource_type="user",
            resource_id=str(user.id),
        )
        return payload.model_dump()

    return run(db, user, "account.profile", key, payload.model_dump(), action)


@router.get("/me/preferences", response_model=Preferences)
def read_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = profile_for(db, user)
    return row.preferences if row else Preferences().model_dump()


@router.put("/me/preferences", response_model=Preferences)
def write_preferences(
    payload: Preferences,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        row = profile_for(db, user, True)
        row.preferences = payload.model_dump()
        record_audit(
            db,
            actor=user.subject,
            action="CustomerPreferencesUpdated",
            resource_type="user",
            resource_id=str(user.id),
        )
        return row.preferences

    return run(db, user, "account.preferences", key, payload.model_dump(), action)


@router.post("/me/devices", response_model=DeviceOutput, status_code=201)
def register_device(
    payload: DeviceInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        db.execute(select(User).where(User.id == user.id).with_for_update())
        count = db.scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.user_id == user.id, Device.revoked.is_(False))
        )
        if count is not None and count >= 50:
            raise HTTPException(409, "Revoke an existing device before registering another")
        device = Device(user_id=user.id, label=payload.label, platform=payload.platform)
        db.add(device)
        db.flush()
        record_audit(
            db,
            actor=user.subject,
            action="DeviceRegistered",
            resource_type="device",
            resource_id=str(device.id),
        )
        return serialize(device)

    return run(db, user, "account.device.register", key, payload.model_dump(), action)


@router.get("/me/devices", response_model=DevicePage)
def devices(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    return {
        "items": [
            serialize(row)
            for row in db.scalars(
                select(Device)
                .where(Device.user_id == user.id)
                .order_by(Device.created_at.desc())
                .limit(limit)
            )
        ]
    }


@router.delete("/me/devices/{device_id}", response_model=DeviceOutput)
def revoke_device(
    device_id: UUID,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    def action():
        db.execute(select(User).where(User.id == user.id).with_for_update())
        device = db.scalar(
            select(Device)
            .where(Device.id == device_id, Device.user_id == user.id)
            .with_for_update()
        )
        if device is None:
            raise HTTPException(404, "Device not found")
        device.revoked = True
        db.execute(
            update(RefreshSession).where(RefreshSession.device_id == device.id).values(revoked=True)
        )
        record_audit(
            db,
            actor=user.subject,
            action="DeviceRevoked",
            resource_type="device",
            resource_id=str(device.id),
        )
        return serialize(device)

    return run(db, user, "account.device.revoke:" + str(device_id), key, {}, action)
