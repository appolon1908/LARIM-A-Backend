from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.marketplace.models import Customer, Provider
from larimia.shared.auth import Principal, Role


def customer_for_principal(db: Session, principal: Principal) -> Customer:
    row = db.scalar(
        select(Customer).where(
            Customer.identity_issuer == principal.issuer,
            Customer.identity_subject == principal.subject,
            Customer.status == "ACTIVE",
        )
    )
    if not row:
        raise HTTPException(403, detail={"code": "CUSTOMER_PROFILE_REQUIRED"})
    return row


def provider_for_principal(db: Session, principal: Principal) -> Provider:
    row = db.scalar(
        select(Provider).where(
            Provider.identity_issuer == principal.issuer,
            Provider.identity_subject == principal.subject,
        )
    )
    if not row:
        raise HTTPException(403, detail={"code": "PROVIDER_PROFILE_REQUIRED"})
    return row


def require_market(principal: Principal, market_code: str) -> None:
    if Role.PLATFORM_ADMIN in principal.roles:
        return
    if principal.market_codes and market_code not in principal.market_codes:
        raise HTTPException(403, detail={"code": "MARKET_FORBIDDEN"})


def require_booking_customer(db: Session, principal: Principal, booking) -> Customer:
    customer = customer_for_principal(db, principal)
    if booking.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    return customer
