import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from larimia.config import Settings
from larimia.main import app


def production_settings(**overrides):
    values = {
        "env": "production",
        "auth_mode": "oidc",
        "oidc_issuer": "https://auth.codestra.co/realms/larimia",
        "oidc_jwks_url": (
            "https://auth.codestra.co/realms/larimia/protocol/openid-connect/certs"
        ),
        "oidc_audience": "larimia-api",
        "oidc_allowed_algorithms": "RS256",
        "cors_origins": "https://app.example.com",
        "enabled_capabilities": "request_intake,quotes",
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "migration_head": "0004",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_demo_auth():
    with pytest.raises(ValidationError):
        production_settings(auth_mode="demo")


def test_production_rejects_noncanonical_identity_host():
    with pytest.raises(ValidationError):
        production_settings(
            oidc_issuer="https://identity.example.org/realms/larimia",
            oidc_jwks_url="https://identity.example.org/jwks.json",
        )


def test_production_rejects_symmetric_oidc_algorithms():
    with pytest.raises(ValidationError):
        production_settings(oidc_allowed_algorithms="HS256")


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError):
        production_settings(cors_origins="*")


def test_production_rejects_payments_with_sandbox_adapter():
    with pytest.raises(ValidationError):
        production_settings(
            enabled_capabilities="request_intake,quotes,payments",
            payment_provider_code="sandbox",
        )


def test_production_requires_immutable_release_identity():
    with pytest.raises(ValidationError):
        production_settings(git_sha="unknown")
    with pytest.raises(ValidationError):
        production_settings(image_digest="unknown")


def test_valid_fail_closed_production_configuration():
    settings = production_settings()
    assert settings.auth_mode == "oidc"
    assert settings.capability_set == {"request_intake", "quotes"}


def test_payment_api_is_disabled_by_default():
    client = TestClient(app)
    response = client.post("/v1/payments/authorize", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CAPABILITY_DISABLED"
