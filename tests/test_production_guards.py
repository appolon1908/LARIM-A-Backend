import pytest
from pydantic import ValidationError

from larimia.config import Settings


def test_production_rejects_demo_auth():
    with pytest.raises(ValidationError):
        Settings(
            env="production",
            auth_mode="demo",
            oidc_issuer="https://id.example.org/",
            oidc_jwks_url="https://id.example.org/.well-known/jwks.json",
        )


def test_production_requires_real_jwks():
    with pytest.raises(ValidationError):
        Settings(
            env="production",
            auth_mode="oidc",
            oidc_issuer="https://id.example.org/",
            oidc_jwks_url="",
        )
