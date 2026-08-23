from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status

from larimia.config import get_settings


class Role(StrEnum):
    CUSTOMER = "customer"
    PROVIDER = "provider"
    DISPATCHER = "dispatcher"
    SUPPORT = "support"
    SAFETY = "safety"
    FINANCE = "finance"
    QUALITY = "quality"
    COMPLIANCE = "compliance"
    CATALOG_MANAGER = "catalog_manager"
    PARTNER_BOOKER = "partner_booker"
    PLATFORM_ADMIN = "platform_admin"


@dataclass(frozen=True)
class Principal:
    subject: str
    issuer: str
    roles: frozenset[Role]
    organization_id: str | None = None
    market_codes: frozenset[str] = frozenset()


@lru_cache(maxsize=8)
def _jwks(url: str) -> dict:
    response = httpx.get(url, timeout=5.0, follow_redirects=False)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
        raise ValueError("OIDC JWKS response is invalid")
    return value


def _allowed_algorithms() -> list[str]:
    settings = get_settings()
    algorithms = [
        value.strip()
        for value in settings.oidc_allowed_algorithms.split(",")
        if value.strip()
    ]
    if not algorithms:
        raise HTTPException(status_code=500, detail={"code": "OIDC_ALGORITHMS_NOT_CONFIGURED"})
    return algorithms


def _signing_key(token: str):
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN_HEADER"}) from exc

    algorithm = header.get("alg")
    if algorithm not in _allowed_algorithms():
        raise HTTPException(status_code=401, detail={"code": "TOKEN_ALGORITHM_NOT_ALLOWED"})

    key_id = header.get("kid")
    if not key_id:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_KEY_ID_REQUIRED"})

    keys = _jwks(settings.oidc_jwks_url).get("keys", [])
    key = next((item for item in keys if item.get("kid") == key_id), None)
    if key is None:
        _jwks.cache_clear()
        keys = _jwks(settings.oidc_jwks_url).get("keys", [])
        key = next((item for item in keys if item.get("kid") == key_id), None)
    if key is None:
        raise HTTPException(status_code=401, detail={"code": "UNKNOWN_SIGNING_KEY"})

    try:
        return jwt.PyJWK.from_dict(key, algorithm=algorithm).key
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail={"code": "INVALID_SIGNING_KEY"}) from exc


def _principal_from_token(token: str) -> Principal:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            _signing_key(token),
            algorithms=_allowed_algorithms(),
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={
                "require": ["aud", "exp", "iat", "iss", "sub"],
                "verify_aud": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_nbf": True,
                "verify_signature": True,
            },
            leeway=settings.oidc_clock_skew_seconds,
        )
    except HTTPException:
        raise
    except (jwt.PyJWTError, httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN"}) from exc

    raw_roles = claims.get("roles") or claims.get("realm_access", {}).get("roles", [])
    roles: set[Role] = set()
    for raw in raw_roles:
        try:
            roles.add(Role(raw))
        except ValueError:
            continue

    markets = claims.get("markets", [])
    if not isinstance(markets, list):
        markets = []

    return Principal(
        subject=str(claims["sub"]),
        issuer=str(claims["iss"]),
        roles=frozenset(roles),
        organization_id=claims.get("org_id"),
        market_codes=frozenset(str(value) for value in markets),
    )


def get_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_demo_subject: str | None = Header(default=None, alias="X-Demo-Subject"),
    x_demo_roles: str | None = Header(default=None, alias="X-Demo-Roles"),
) -> Principal:
    settings = get_settings()
    if settings.auth_mode == "oidc":
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
        return _principal_from_token(authorization.split(" ", 1)[1].strip())

    if settings.env.lower() == "production":
        raise HTTPException(status_code=500, detail={"code": "UNSAFE_AUTH_CONFIGURATION"})

    if not x_demo_subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_REQUIRED"},
        )

    parsed: set[Role] = set()
    for raw in (x_demo_roles or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed.add(Role(raw))
        except ValueError:
            continue

    return Principal(subject=x_demo_subject, issuer="demo", roles=frozenset(parsed))


def require_roles(*allowed: Role):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if Role.PLATFORM_ADMIN in principal.roles or principal.roles.intersection(allowed):
            return principal
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})

    return dependency
