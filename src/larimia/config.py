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
    auth_mode: str = "local"
    local_jwt_secret: str = Field(default="", repr=False)
    seed_password: str = Field(default="", repr=False)
    azure_client_id: str = ""
    storage_mode: str = "local"
    azure_storage_url: str = ""
    azure_storage_container: str = "private-documents"
    event_transport: str = "local"
    service_bus_namespace: str = ""
    service_bus_queue: str = "marketplace-events"
    storage_root: str = "/var/lib/larimia/storage"
    payment_webhook_secret: str = Field(default="", repr=False)
    rate_limit_per_minute: int = 300
    notification_mode: str = "disabled"
    notification_relay_url: str = ""
    notification_relay_token: str = Field(default="", repr=False)
    payment_mode: str = "mock"
    dispatch_speed_kmh: float = Field(default=25, ge=5, le=130)
    dispatch_road_factor: float = Field(default=1.3, ge=1, le=3)
    dispatch_offer_seconds: int = 60
    dispatch_batch_size: int = 3
    dispatch_weights: dict[str, float] = {
        "distance": 0.4,
        "rating": 0.2,
        "completion": 0.3,
        "workload": 0.1,
        "eta": 0.2,
        "acceptance": 0.1,
        "specialization": 0.05,
        "fairness": 0.05,
        "market_balance": 0.05,
    }
    certification_enabled: bool = False
    certification_tokens_json: str = Field(default="{}", repr=False)
    build_version: str = "0.3.0"
    database_url: str = Field(
        default="postgresql+psycopg://larimia:larimia@localhost:5432/larimia", repr=False
    )
    runtime_database_url: str = Field(default="", repr=False)
    database_url_file: str = ""
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    redis_url_file: str = ""
    celery_broker_url: str = Field(default="amqp://guest:guest@localhost:5672//", repr=False)
    celery_broker_url_file: str = ""
    cors_origins: str = "http://localhost:3000"
    workforce_oidc_issuer: str = ""
    workforce_oidc_audience: str = ""
    workforce_oidc_jwks_url: str = ""
    telemetry_otlp_endpoint: str = ""
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
        if self.auth_mode not in {"local", "oidc", "demo"}:
            raise ValueError("Unsupported identity adapter")
        if self.storage_mode not in {"local", "azure"} or self.event_transport not in {
            "local",
            "azure",
        }:
            raise ValueError("Unknown storage or event transport")
        if self.storage_mode == "azure" and not self.azure_storage_url.startswith("https://"):
            raise ValueError("Azure private storage requires an HTTPS account URL")
        if self.event_transport == "azure" and not self.service_bus_namespace.endswith(
            ".servicebus.windows.net"
        ):
            raise ValueError("Azure Service Bus requires a fully qualified namespace")
        if self.notification_mode not in {"disabled", "local", "relay"}:
            raise ValueError("Unknown notification adapter")
        if self.notification_mode == "local" and self.env != "development":
            raise ValueError("Local notification simulation is development-only")
        if self.notification_mode == "relay":
            from urllib.parse import urlsplit

            endpoint = urlsplit(self.notification_relay_url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
                or not self.notification_relay_token
            ):
                raise ValueError("Notification relay requires a configured HTTPS URL and token")
        if self.payment_mode != "mock":
            raise ValueError("No live payment gateway has been installed; use explicit mock mode")
        if self.local_jwt_secret and len(self.local_jwt_secret) < 32:
            raise ValueError("Local JWT signing keys must be at least 32 characters")
        import math

        required_weights = {"distance", "rating", "completion", "workload"}
        optional_weights = {"eta", "acceptance", "specialization", "fairness", "market_balance"}
        if (
            not required_weights.issubset(self.dispatch_weights)
            or not set(self.dispatch_weights).issubset(required_weights | optional_weights)
            or any(not math.isfinite(v) or v < 0 for v in self.dispatch_weights.values())
            or sum(self.dispatch_weights.values()) <= 0
        ):
            raise ValueError("Dispatch weights must be known, finite and nonnegative")
        if self.dispatch_offer_seconds <= 0 or not 1 <= self.dispatch_batch_size <= 50:
            raise ValueError("Invalid dispatch configuration")
        if self.env.lower() in {"staging", "production"}:
            if "*" in self.cors_origin_list:
                raise ValueError("Staging/production forbids wildcard CORS")
            if self.auth_mode != "oidc":
                raise ValueError("Production requires LARIMIA_AUTH_MODE=oidc")
            if "example.com" in self.oidc_issuer:
                raise ValueError("Production requires a real OIDC issuer")
            if not self.oidc_issuer.startswith("https://"):
                raise ValueError("OIDC issuer must use HTTPS")
            if not self.oidc_jwks_url.startswith("https://"):
                raise ValueError("Production requires LARIMIA_OIDC_JWKS_URL")
            if (
                "sslmode=require" not in self.database_url
                and "sslmode=verify-full" not in self.database_url
            ):
                raise ValueError("Staging database connections require TLS")
            if self.workforce_oidc_issuer and (
                not self.workforce_oidc_issuer.startswith("https://")
                or not self.workforce_oidc_jwks_url.startswith("https://")
                or not self.workforce_oidc_audience
            ):
                raise ValueError(
                    "Workforce identity requires explicit HTTPS issuer, JWKS and audience"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
