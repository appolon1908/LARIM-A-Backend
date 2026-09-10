from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.marketplace.models import CustomerAddress, DeviceRegistration
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.db import get_db


router = APIRouter()


class AddressCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    place_type: str = Field(min_length=1, max_length=32)
    address_line_1: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    country_code: str = Field(min_length=2, max_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    access_notes: str | None = Field(default=None, max_length=2_000)


class DeviceCreate(BaseModel):
    platform: str = Field(pattern=r"^(ios|android|web)$")
    token: str = Field(min_length=8, max_length=512)


@router.get("/me")
def me(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    return {
        "id": str(customer.id),
        "market_code": customer.market_code,
        "preferred_language": customer.preferred_language,
        "status": customer.status,
    }


@router.get("/me/addresses")
def addresses(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    rows = list(
        db.scalars(
            select(CustomerAddress)
            .where(
                CustomerAddress.customer_id == customer.id,
                CustomerAddress.active.is_(True),
            )
            .order_by(CustomerAddress.label, CustomerAddress.id)
        )
    )
    return {
        "items": [
            {
                "id": str(address.id),
                "label": address.label,
                "place_type": address.place_type,
                "address_line_1": address.address_line_1,
                "city": address.city,
                "country_code": address.country_code,
                "latitude": float(address.latitude),
                "longitude": float(address.longitude),
                "access_notes": address.access_notes,
            }
            for address in rows
        ]
    }


@router.post("/me/addresses", status_code=201)
def add_address(
    payload: AddressCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    address = CustomerAddress(
        customer_id=customer.id,
        active=True,
        **payload.model_dump(),
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return {"id": str(address.id)}


@router.post("/me/devices", status_code=201)
def register_device(
    payload: DeviceCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer_for_principal(db, principal)
    row = db.scalar(
        select(DeviceRegistration)
        .where(DeviceRegistration.token == payload.token)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if row is None:
        row = DeviceRegistration(
            identity_subject=principal.subject,
            platform=payload.platform,
            token=payload.token,
            active=True,
            updated_at=now,
        )
        db.add(row)
    elif row.identity_subject != principal.subject:
        # A push token must not be silently reassigned between identities.
        raise HTTPException(409, detail={"code": "DEVICE_TOKEN_ALREADY_REGISTERED"})
    else:
        row.platform = payload.platform
        row.active = True
        row.updated_at = now

    db.commit()
    return {"status": "registered"}
