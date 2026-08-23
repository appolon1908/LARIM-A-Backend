import uuid
from dataclasses import dataclass

from larimia.adapters.contracts import PaymentProvider
from larimia.config import get_settings


class PaymentConfigurationError(RuntimeError):
    pass


@dataclass
class SandboxPaymentProvider:
    code: str = "sandbox"

    async def authorize(
        self,
        *,
        token: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> dict:
        return {
            "external_id": f"pi_{uuid.uuid4().hex}",
            "status": "AUTHORIZED",
            "amount_minor": amount_minor,
            "currency": currency,
        }

    async def capture(
        self,
        *,
        external_id: str,
        amount_minor: int | None = None,
    ) -> dict:
        return {
            "external_id": f"ch_{uuid.uuid4().hex}",
            "status": "CAPTURED",
            "amount_minor": amount_minor,
        }

    async def refund(
        self,
        *,
        external_id: str,
        amount_minor: int,
        reason: str,
    ) -> dict:
        return {
            "external_id": f"re_{uuid.uuid4().hex}",
            "status": "PENDING",
            "amount_minor": amount_minor,
        }


def payment_provider() -> PaymentProvider:
    settings = get_settings()
    provider_code = settings.payment_provider_code.strip().lower()

    if provider_code == "sandbox":
        if settings.env.lower() == "production":
            raise PaymentConfigurationError(
                "Sandbox payment provider is forbidden in production"
            )
        return SandboxPaymentProvider()

    if provider_code in {"", "disabled"}:
        raise PaymentConfigurationError("Payments are not configured")

    raise PaymentConfigurationError(
        f"Payment provider {provider_code!r} has no registered adapter"
    )
