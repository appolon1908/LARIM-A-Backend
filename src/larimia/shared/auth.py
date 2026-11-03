import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError

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
    session_id: str | None = None


@lru_cache(maxsize=4)
def _jwks(url: str, epoch: int) -> dict:
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()


def _principal_from_token(token: str) -> Principal:
    settings = get_settings()
    issuer, audience, jwks_url = (
        settings.oidc_issuer,
        settings.oidc_audience,
        settings.oidc_jwks_url,
    )
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        if (
            settings.workforce_oidc_issuer
            and unverified.get("iss") == settings.workforce_oidc_issuer
        ):
            issuer, audience, jwks_url = (
                settings.workforce_oidc_issuer,
                settings.workforce_oidc_audience,
                settings.workforce_oidc_jwks_url,
            )
        header = jwt.get_unverified_header(token)
        keys = _jwks(jwks_url, int(time.time() // 300)).get("keys", [])
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if not key:
            _jwks.cache_clear()
            keys = _jwks(jwks_url, int(time.time() // 300)).get("keys", [])
            key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if not key:
            raise HTTPException(status_code=401, detail={"code": "UNKNOWN_SIGNING_KEY"})

        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(key).key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except (JWTError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN"}) from exc

    roles = set()
    raw_roles = claims.get("roles", []) or claims.get("realm_access", {}).get("roles", [])
    for raw in raw_roles:
        try:
            roles.add(Role(raw))
        except ValueError:
            pass

    return Principal(
        subject=str(claims["sub"]),
        issuer=str(claims["iss"]),
        roles=frozenset(roles),
        organization_id=claims.get("org_id"),
        market_codes=frozenset(claims.get("markets", [])),
    )


bearer_scheme = HTTPBearer(auto_error=False)


def get_principal(
    authorization: str | None = Header(
        default=None, alias="Authorization", include_in_schema=False
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_demo_subject: str | None = Header(
        default=None, alias="X-Demo-Subject", include_in_schema=False
    ),
    x_demo_roles: str | None = Header(default=None, alias="X-Demo-Roles", include_in_schema=False),
) -> Principal:
    settings = get_settings()
    if settings.auth_mode == "local":
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or not settings.local_jwt_secret
        ):
            raise HTTPException(401, "Authentication required")
        try:
            claims = jwt.decode(
                authorization[7:],
                settings.local_jwt_secret,
                algorithms=["HS256"],
                issuer="larimia-local",
                audience="larimia-api",
                options={"require": ["exp", "sub"]},
            )
        except JWTError as exc:
            raise HTTPException(401, "Invalid token") from exc
        return Principal(
            subject=claims["sub"],
            issuer="larimia-local",
            roles=frozenset(),
            session_id=claims.get("sid"),
        )
    if settings.auth_mode == "oidc":
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
        return _principal_from_token(authorization.split(" ", 1)[1].strip())

    if settings.env.lower() in {"staging", "production"}:
        raise HTTPException(status_code=500, detail={"code": "UNSAFE_AUTH_CONFIGURATION"})

    if not x_demo_subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "AUTH_REQUIRED"}
        )
    parsed: set[Role] = set()
    for raw in (x_demo_roles or "").split(","):
        raw = raw.strip()
        if raw:
            try:
                parsed.add(Role(raw))
            except ValueError:
                pass
    return Principal(subject=x_demo_subject, issuer="demo", roles=frozenset(parsed))


def require_roles(*allowed: Role):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if Role.PLATFORM_ADMIN in principal.roles or principal.roles.intersection(allowed):
            return principal
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})

    return dependency
