import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from larimia.config import Settings, get_settings
from larimia.shared import auth
from larimia.shared.auth import _principal_from_token


@pytest.fixture
def identity(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "test-key"
    monkeypatch.setattr(auth, "_jwks", lambda *_: {"keys": [public]})
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer", "https://customer.identity.test/")
    monkeypatch.setattr(settings, "oidc_audience", "larimia-customer")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://customer.identity.test/jwks")
    return key, {
        "sub": "customer-test",
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }


def test_valid_oidc(identity):
    key, claims = identity
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
    assert _principal_from_token(token).subject == "customer-test"


@pytest.mark.parametrize(
    "field,value", [("iss", "https://untrusted.test/"), ("aud", "other-api"), ("exp", 1)]
)
def test_oidc_rejects_invalid_claims(identity, field, value):
    key, claims = identity
    token = jwt.encode(
        {**claims, field: value}, key, algorithm="RS256", headers={"kid": "test-key"}
    )
    with pytest.raises(HTTPException) as caught:
        _principal_from_token(token)
    assert caught.value.status_code == 401


def test_oidc_requires_expiration(identity):
    key, claims = identity
    del claims["exp"]
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(HTTPException):
        _principal_from_token(token)


def test_oidc_rejects_other_signature(identity):
    key, claims = identity
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(HTTPException):
        _principal_from_token(token)


def test_oidc_rejects_algorithm_confusion(identity):
    _, claims = identity
    token = jwt.encode(
        claims,
        "isolated-hmac-fixture-long-enough-32",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    with pytest.raises(HTTPException):
        _principal_from_token(token)


def test_staging_rejects_wildcard_and_plaintext_database():
    from pydantic import ValidationError

    values = dict(
        _env_file=None,
        env="staging",
        auth_mode="oidc",
        oidc_issuer="https://identity.test/",
        oidc_jwks_url="https://identity.test/keys",
    )
    with pytest.raises(ValidationError):
        Settings(**values, cors_origins="*")
    with pytest.raises(ValidationError):
        Settings(**values, database_url="postgresql+psycopg://u:p@localhost/db")
