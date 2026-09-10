import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from larimia.adapters.contracts import PaymentProvider
from larimia.config import get_settings
from larimia.payments.errors import PaymentProviderError
from larimia.payments.paypal import PayPalPaymentProvider
from larimia.payments.stripe import StripePaymentProvider


class PaymentConfigurationError(RuntimeError):
    pass


@dataclass
class SandboxPaymentProvider:
    code: str = "sandbox"

    async def create_checkout(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict:
        return {
            "external_order_id": f"order_{uuid.uuid4().hex}",
            "approve_url": "https://example.invalid/sandbox-approval",
            "status": "CREATED",
        }

    async def authorize(
        self,
        *,
        token: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict:
        external_id = f"pi_{uuid.uuid4().hex}"
        return {
            "external_id": external_id,
            "provider_authorization_id": external_id,
            "status": "AUTHORIZED",
            "raw_status": "AUTHORIZED",
        }

    async def capture(
        self,
        *,
        external_id: str,
        amount_minor: int | None,
        currency: str,
        idempotency_key: str,
    ) -> dict:
        return {
            "external_id": external_id,
            "provider_capture_id": f"ch_{uuid.uuid4().hex}",
            "status": "CAPTURED",
            "raw_status": "CAPTURED",
        }

    async def void(self, *, external_id: str, idempotency_key: str) -> dict:
        return {"external_id": external_id, "status": "VOIDED", "raw_status": "VOIDED"}

    async def refund(
        self,
        *,
        external_id: str,
        amount_minor: int,
        currency: str,
        reason: str,
        idempotency_key: str,
    ) -> dict:
        return {
            "external_id": f"re_{uuid.uuid4().hex}",
            "status": "SUCCEEDED",
            "raw_status": "SUCCEEDED",
        }

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> dict:
        settings = get_settings()
        timestamp = headers.get("x-webhook-timestamp") or headers.get("X-Webhook-Timestamp")
        signature = headers.get("x-webhook-signature") or headers.get("X-Webhook-Signature")
        secret = settings.webhook_secret_map.get("payments:sandbox")
        if not timestamp or not signature or not isinstance(secret, str):
            raise PaymentProviderError("SANDBOX_SIGNATURE_REQUIRED")
        if abs(int(time.time()) - int(timestamp)) > settings.webhook_replay_window_seconds:
            raise PaymentProviderError("SANDBOX_WEBHOOK_REPLAY_WINDOW")
        expected = hmac.new(
            secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.removeprefix("sha256=")):
            raise PaymentProviderError("SANDBOX_SIGNATURE_INVALID")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise PaymentProviderError("SANDBOX_PAYLOAD_INVALID")
        return value

    def translate_webhook(self, payload: dict) -> dict:
        return payload


def configured_payment_provider_codes() -> set[str]:
    return set(get_settings().payment_provider_set)


def payment_provider(provider_code: str | None = None) -> PaymentProvider:
    settings = get_settings()
    code = (provider_code or settings.payment_provider_code).strip().lower()
    if code not in settings.payment_provider_set:
        raise PaymentConfigurationError(f"Payment provider {code!r} is not enabled")
    if code == "sandbox":
        if settings.env.lower() == "production":
            raise PaymentConfigurationError("Sandbox payment provider is forbidden in production")
        return SandboxPaymentProvider()
    if code == "stripe":
        if not settings.stripe_secret_key.get_secret_value():
            raise PaymentConfigurationError("Stripe secret key is not configured")
        return StripePaymentProvider(settings)
    if code == "paypal":
        if not settings.paypal_client_id or not settings.paypal_client_secret.get_secret_value():
            raise PaymentConfigurationError("PayPal credentials are not configured")
        return PayPalPaymentProvider(settings)
    raise PaymentConfigurationError(f"Payment provider {code!r} has no registered adapter")


def public_payment_configuration() -> dict:
    settings = get_settings()
    providers: list[dict] = []
    for code in sorted(settings.payment_provider_set):
        if code == "stripe":
            providers.append(
                {
                    "code": "stripe",
                    "publishable_key": settings.stripe_publishable_key,
                    "capture_mode": "manual",
                }
            )
        elif code == "paypal":
            providers.append(
                {
                    "code": "paypal",
                    "client_id": settings.paypal_client_id,
                    "environment": settings.paypal_environment,
                    "intent": "authorize",
                }
            )
        elif code == "sandbox" and settings.env.lower() != "production":
            providers.append({"code": "sandbox", "capture_mode": "manual"})
    return {"primary": settings.payment_provider_code, "providers": providers}
