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
        "oidc_jwks_url": "https://auth.codestra.co/realms/larimia/protocol/openid-connect/certs",
        "oidc_audience": "larimia-api",
        "oidc_allowed_algorithms": "RS256",
        "cors_origins": "https://app.example.com",
        "enabled_capabilities": "request_intake,quotes",
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "migration_head": "0007",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_demo_auth():
    with pytest.raises(ValidationError):
        production_settings(auth_mode="demo")


def test_production_rejects_noncanonical_identity_host():
    with pytest.raises(ValidationError):
        production_settings(oidc_issuer="https://identity.example.org/realms/larimia", oidc_jwks_url="https://identity.example.org/jwks.json")


def test_production_rejects_symmetric_oidc_algorithms():
    with pytest.raises(ValidationError):
        production_settings(oidc_allowed_algorithms="HS256")


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError):
        production_settings(cors_origins="*")


def test_production_rejects_unknown_capability():
    with pytest.raises(ValidationError):
        production_settings(enabled_capabilities="request_intake,not-real")


def test_production_rejects_payments_with_sandbox_adapter():
    with pytest.raises(ValidationError):
        production_settings(enabled_capabilities="request_intake,quotes,payments", payment_provider_code="sandbox", payment_provider_codes="sandbox")


def test_production_accepts_complete_stripe_configuration():
    settings = production_settings(
        enabled_capabilities="request_intake,quotes,payments",
        payment_provider_code="stripe",
        payment_provider_codes="stripe",
        stripe_secret_key="sk_live_example",
        stripe_publishable_key="pk_live_example",
        stripe_webhook_secret="whsec_example",
        stripe_api_version="2025-06-30.basil",
    )
    assert settings.payment_provider_set == {"stripe"}


def test_production_accepts_complete_paypal_configuration():
    settings = production_settings(
        enabled_capabilities="request_intake,quotes,payments",
        payment_provider_code="paypal",
        payment_provider_codes="paypal",
        paypal_client_id="client",
        paypal_client_secret="secret",
        paypal_webhook_id="WH-123",
        paypal_environment="live",
        paypal_return_url="https://app.example.com/paypal/return",
        paypal_cancel_url="https://app.example.com/paypal/cancel",
    )
    assert settings.payment_provider_set == {"paypal"}


def test_production_requires_immutable_release_identity():
    with pytest.raises(ValidationError):
        production_settings(git_sha="unknown")
    with pytest.raises(ValidationError):
        production_settings(image_digest="unknown")
    with pytest.raises(ValidationError):
        production_settings(migration_head="0006")


def test_valid_fail_closed_production_configuration():
    settings = production_settings()
    assert settings.auth_mode == "oidc"
    assert settings.capability_set == {"request_intake", "quotes"}


def test_payment_api_is_disabled_by_default():
    client = TestClient(app)
    response = client.post("/v1/payments/authorize", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CAPABILITY_DISABLED"
