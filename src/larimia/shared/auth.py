from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import httpx
import jwt
from jwt import PyJWK, PyJWTError
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

@lru_cache(maxsize=4)
def _jwks(url: str) -> dict:
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()

def _principal_from_token(token: str) -> Principal:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm not in settings.oidc_algorithm_list:
            raise HTTPException(status_code=401, detail={"code": "UNSUPPORTED_SIGNING_ALGORITHM"})
        keys = _jwks(settings.oidc_jwks_url).get("keys", [])
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if not key:
            _jwks.cache_clear()
            keys = _jwks(settings.oidc_jwks_url).get("keys", [])
            key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if not key:
            raise HTTPException(status_code=401, detail={"code": "UNKNOWN_SIGNING_KEY"})

        claims = jwt.decode(
            token,
            PyJWK.from_dict(key).key,
            algorithms=settings.oidc_algorithm_list,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"verify_at_hash": False},
        )
    except (PyJWTError, ValueError, KeyError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN"}) from exc

    roles = set()
    raw_roles = claims.get("roles", []) or claims.get("realm_access", {}).get("roles", [])
    for raw in raw_roles:
        try: roles.add(Role(raw))
        except ValueError: pass

    return Principal(
        subject=str(claims["sub"]),
        issuer=str(claims["iss"]),
        roles=frozenset(roles),
        organization_id=claims.get("org_id"),
        market_codes=frozenset(claims.get("markets", [])),
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "AUTH_REQUIRED"})
    parsed: set[Role] = set()
    for raw in (x_demo_roles or "").split(","):
        raw = raw.strip()
        if raw:
            try: parsed.add(Role(raw))
            except ValueError: pass
    return Principal(subject=x_demo_subject, issuer="demo", roles=frozenset(parsed))

def require_roles(*allowed: Role):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if Role.PLATFORM_ADMIN in principal.roles or principal.roles.intersection(allowed):
            return principal
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})
    return dependency
