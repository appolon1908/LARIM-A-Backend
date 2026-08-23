import uuid
from dataclasses import dataclass

from larimia.config import get_settings


class PaymentConfigurationError(RuntimeError):
    pass


@dataclass
class SandboxPaymentProvider:
    code: str = "sandbox"

    async def authorize(
        self, *, token: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> dict:
        return {"external_id": f"pi_{uuid.uuid4().hex}", "status": "AUTHORIZED"}

    async def capture(self, *, external_id: str, amount_minor: int | None = None) -> dict:
        return {
            "external_id": f"ch_{uuid.uuid4().hex}",
            "status": "CAPTURED",
            "amount_minor": amount_minor,
        }

    async def refund(self, *, external_id: str, amount_minor: int, reason: str) -> dict:
        return {"external_id": f"re_{uuid.uuid4().hex}", "status": "PENDING"}


def payment_provider():
    settings = get_settings()
    if settings.payment_provider_code == "sandbox":
        if settings.env.lower() == "production":
            raise PaymentConfigurationError("Sandbox payment provider is forbidden in production")
        return SandboxPaymentProvider()
    raise PaymentConfigurationError(
        f"Payment provider {settings.payment_provider_code!r} is not configured"
    )
