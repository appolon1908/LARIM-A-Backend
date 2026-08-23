from functools import lru_cache
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


RISKY_CAPABILITIES = {
    "automatic_assignment",
    "matching",
    "memberships",
    "messaging",
    "partners",
    "payments",
    "payouts",
    "provider_self_service",
    "reviews",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LARIMIA_",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "development"
    auth_mode: str = "demo"
    database_url: str = "postgresql+psycopg://larimia:larimia@localhost:5432/larimia"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"
    cors_origins: str = "http://localhost:3000"

    oidc_issuer: str = "https://auth.codestra.co/realms/larimia"
    oidc_audience: str = "larimia-api"
    oidc_jwks_url: str = "https://auth.codestra.co/realms/larimia/protocol/openid-connect/certs"
    oidc_allowed_algorithms: str = "RS256"
    oidc_clock_skew_seconds: int = 30

    log_level: str = "INFO"
    payment_provider_code: str = "sandbox"
    payout_provider_code: str = "disabled"
    webhook_secrets_json: str = "{}"
    websocket_redis_url: str = ""
    max_webhook_bytes: int = 1_048_576

    # Fail closed by default. High-risk capabilities must be enabled explicitly
    # after their adapter, authorization, reconciliation and operational gates pass.
    enabled_capabilities: str = "request_intake,quotes"

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def capability_set(self) -> set[str]:
        return {
            value.strip()
            for value in self.enabled_capabilities.split(",")
            if value.strip()
        }

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [
            value.strip()
            for value in self.oidc_allowed_algorithms.split(",")
            if value.strip()
        ]

    @model_validator(mode="after")
    def production_guards(self):
        if self.max_webhook_bytes < 1 or self.max_webhook_bytes > 10 * 1024 * 1024:
            raise ValueError("LARIMIA_MAX_WEBHOOK_BYTES must be between 1 byte and 10 MiB")

        algorithms = self.oidc_algorithm_list
        if not algorithms:
            raise ValueError("At least one OIDC signing algorithm is required")
        if any(value.lower() == "none" or value.upper().startswith("HS") for value in algorithms):
            raise ValueError("OIDC must use configured asymmetric signing algorithms")

        if self.env.lower() != "production":
            return self

        if self.auth_mode != "oidc":
            raise ValueError("Production requires LARIMIA_AUTH_MODE=oidc")

        issuer = urlparse(self.oidc_issuer)
        jwks = urlparse(self.oidc_jwks_url)
        if issuer.scheme != "https" or not issuer.netloc:
            raise ValueError("Production requires an HTTPS OIDC issuer")
        if jwks.scheme != "https" or not jwks.netloc:
            raise ValueError("Production requires an HTTPS OIDC JWKS URL")
        if issuer.hostname != "auth.codestra.co" or jwks.hostname != "auth.codestra.co":
            raise ValueError("Production OIDC must use canonical host auth.codestra.co")
        if not self.oidc_audience.strip():
            raise ValueError("Production requires LARIMIA_OIDC_AUDIENCE")

        if not self.cors_origin_list or "*" in self.cors_origin_list:
            raise ValueError("Production requires explicit CORS origins")
        for origin in self.cors_origin_list:
            parsed = urlparse(origin)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("Production CORS origins must be HTTPS URLs")

        capabilities = self.capability_set
        if "payments" in capabilities and self.payment_provider_code in {"sandbox", "disabled", ""}:
            raise ValueError("Payments cannot be enabled without a production payment provider")
        if "payouts" in capabilities and self.payout_provider_code in {"sandbox", "disabled", ""}:
            raise ValueError("Payouts cannot be enabled without a production payout provider")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
