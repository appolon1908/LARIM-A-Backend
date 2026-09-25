import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.shared.auth import Principal, get_principal
from larimia.shared.db import get_db

from .models import User, now

PERMISSIONS = {
    "customer": {"booking.create", "booking.read.own", "review.create", "case.create"},
    "provider": {
        "provider.self",
        "provider.offer.accept",
        "provider.location.update",
        "case.create",
    },
    "support": {"support.ticket.manage", "booking.read", "case.create"},
    "dispatcher": {"booking.dispatch", "booking.read", "provider.read"},
    "finance": {"payment.refund", "finance.read", "finance.payout.approve"},
    "safety": {"safety.incident.manage", "booking.read"},
    "catalog_manager": {"catalog.manage", "pricing.manage"},
    "operations_manager": {"booking.read", "booking.dispatch", "provider.application.review"},
    "platform_admin": {"*"},
    "administrator": {"*"},
    "super_admin": {"*"},
}

# Product identity and workforce permissions remain distinct; aliases normalize Entra app roles.
for alias, original in {
    "CUSTOMER": "customer",
    "PROVIDER": "provider",
    "SUPPORT_AGENT": "support",
    "DISPATCHER": "dispatcher",
    "FINANCE_AGENT": "finance",
    "SAFETY_AGENT": "safety",
    "CATALOG_MANAGER": "catalog_manager",
    "OPERATIONS_MANAGER": "operations_manager",
    "ADMINISTRATOR": "administrator",
    "SUPER_ADMIN": "super_admin",
}.items():
    PERMISSIONS[alias] = PERMISSIONS[original]


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    raw = base64.b64decode(encoded)
    actual = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
    return hmac.compare_digest(raw[16:], actual)


def issue_token(user: User, session_id: UUID | None = None) -> str:
    settings = get_settings()
    if settings.auth_mode != "local" or not settings.local_jwt_secret:
        raise HTTPException(503, "Local identity is disabled")
    return jwt.encode(
        {
            "sub": user.subject,
            **({"sid": str(session_id)} if session_id else {}),
            "iss": "larimia-local",
            "aud": "larimia-api",
            "exp": now() + timedelta(minutes=30),
            "iat": now(),
        },
        settings.local_jwt_secret,
        algorithm="HS256",
    )


def current_user(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> User:
    user = db.scalar(
        select(User).where(User.subject == principal.subject, User.issuer == principal.issuer)
    )
    if not user or not user.active:
        raise HTTPException(403, "Account is not provisioned or is disabled")
    if principal.issuer == "larimia-local" and principal.session_id:
        from .models import Device, RefreshSession

        try:
            session_id = UUID(principal.session_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise HTTPException(401, "Invalid session") from exc
        session = db.get(RefreshSession, session_id)
        if (
            not session
            or session.user_id != user.id
            or session.revoked
            or session.expires_at <= now()
        ):
            raise HTTPException(401, "Session revoked or expired")
        if session.device_id:
            device = db.get(Device, session.device_id)
            if not device or device.user_id != user.id or device.revoked:
                raise HTTPException(401, "Device revoked")
    settings = get_settings()
    if settings.env in {"staging", "production"}:
        workforce = any(role.lower() not in {"customer", "provider"} for role in user.roles)
        if workforce and principal.issuer != settings.workforce_oidc_issuer:
            raise HTTPException(403, "Workforce identity authority is required")
    return user


def allowed(user: User, permission: str) -> bool:
    grants = set().union(*(PERMISSIONS.get(role, set()) for role in user.roles))
    return "*" in grants or permission in grants


def require(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if not allowed(user, permission):
            raise HTTPException(403, "Permission denied")
        return user

    return dependency


def new_session(db: Session, user: User, device_id: UUID | None = None) -> dict:
    from .models import Device, RefreshSession

    # All device/session mutations serialize on the owner first.
    owner = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if owner is None or not owner.active:
        raise HTTPException(401, "Account disabled")
    if device_id:
        device = db.get(Device, device_id)
        if device is None or device.user_id != user.id or device.revoked:
            raise HTTPException(401, "Device unavailable")
        device.last_seen_at = now()
    raw = secrets.token_urlsafe(48)
    session = RefreshSession(
        user_id=user.id,
        device_id=device_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=now() + timedelta(days=7),
    )
    db.add(session)
    db.flush()
    return {
        "access_token": issue_token(user, session.id),
        "refresh_token": raw,
        "token_type": "bearer",
        "expires_in": 1800,
    }
