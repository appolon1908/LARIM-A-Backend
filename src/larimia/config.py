from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    oidc_issuer: str = "https://identity.example.com/"
    oidc_audience: str = "larimia-api"
    oidc_jwks_url: str = ""
    log_level: str = "INFO"
    payment_provider_code: str = "sandbox"
    webhook_secrets_json: str = "{}"
    websocket_redis_url: str = ""
    max_webhook_bytes: int = 1048576
    enabled_capabilities: str = "request_intake,provider_self_service,matching,quotes,messaging,reviews,instant_booking,memberships,partners"

    @property
    def cors_origin_list(self) -> list[str]:
        return [v.strip() for v in self.cors_origins.split(",") if v.strip()]

    @model_validator(mode="after")
    def production_guards(self):
        if self.env.lower() == "production":
            if self.auth_mode != "oidc":
                raise ValueError("Production requires LARIMIA_AUTH_MODE=oidc")
            if "example.com" in self.oidc_issuer:
                raise ValueError("Production requires a real OIDC issuer")
            if not self.oidc_jwks_url:
                raise ValueError("Production requires LARIMIA_OIDC_JWKS_URL")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
