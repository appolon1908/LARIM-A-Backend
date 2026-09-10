from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .secret_files import apply_secret_files


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LARIMIA_",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    env: str = "development"
    auth_mode: str = "demo"
    database_url: str = Field(
        default="postgresql+psycopg://larimia:larimia@localhost:5432/larimia", repr=False
    )
    database_url_file: str = ""
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    redis_url_file: str = ""
    celery_broker_url: str = Field(default="amqp://guest:guest@localhost:5672//", repr=False)
    celery_broker_url_file: str = ""
    cors_origins: str = "http://localhost:3000"
    oidc_issuer: str = "https://identity.example.com/"
    oidc_audience: str = "larimia-api"
    oidc_jwks_url: str = ""
    log_level: str = "INFO"
    enabled_capabilities: str = (
        "request_intake,provider_self_service,matching,quotes,messaging,reviews,"
        "instant_booking,memberships,partners"
    )

    @model_validator(mode="after")
    def load_secret_files(self) -> "Settings":
        apply_secret_files(self, ("database_url", "redis_url", "celery_broker_url"))
        return self

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
