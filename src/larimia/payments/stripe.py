import hashlib
import hmac
import json
import time
from collections.abc import Mapping

import httpx

from larimia.config import Settings
from larimia.payments.errors import PaymentProviderError


class StripePaymentProvider:
    code = "stripe"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_base = settings.stripe_api_base.rstrip("/")

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.stripe_secret_key.get_secret_value()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if self.settings.stripe_api_version:
            headers["Stripe-Version"] = self.settings.stripe_api_version
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.payment_http_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.api_base}{path}",
                    data=data,
                    headers=self._headers(idempotency_key),
                )
        except httpx.TimeoutException as exc:
            raise PaymentProviderError("STRIPE_TIMEOUT", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderError("STRIPE_NETWORK_ERROR", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentProviderError(
                "STRIPE_INVALID_RESPONSE",
                retryable=response.status_code >= 500,
                http_status=response.status_code,
            ) from exc
        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            provider_code = error.get("code") if isinstance(error, dict) else None
            raise PaymentProviderError(
                f"STRIPE_{str(provider_code or 'REQUEST_FAILED').upper()}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                http_status=response.status_code,
            )
        if not isinstance(payload, dict):
            raise PaymentProviderError("STRIPE_INVALID_RESPONSE")
        return payload

    @staticmethod
    def _intent_status(value: str) -> str:
        return {
            "requires_capture": "AUTHORIZED",
            "requires_action": "REQUIRES_ACTION",
            "processing": "PROCESSING",
            "succeeded": "CAPTURED",
            "canceled": "VOIDED",
            "requires_payment_method": "AUTHORIZATION_FAILED",
        }.get(value, "AUTHORIZATION_PENDING")

    async def create_checkout(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict:
        raise PaymentProviderError("STRIPE_CHECKOUT_NOT_REQUIRED")

    async def authorize(
        self,
        *,
        token: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict:
        data = {
            "amount": str(amount_minor),
            "currency": currency.lower(),
            "payment_method": token,
            "confirm": "true",
            "capture_method": "manual",
            "automatic_payment_methods[enabled]": "true",
            "automatic_payment_methods[allow_redirects]": "never",
            "use_stripe_sdk": "true",
            "metadata[booking_id]": str(reference["booking_id"]),
            "metadata[booking_number]": str(reference.get("booking_number", "")),
        }
        payload = await self._request(
            "POST",
            "/payment_intents",
            data=data,
            idempotency_key=idempotency_key,
        )
        raw_status = str(payload.get("status", ""))
        result = {
            "external_id": payload.get("id"),
            "provider_authorization_id": payload.get("id"),
            "provider_payment_method_id": payload.get("payment_method"),
            "provider_customer_id": payload.get("customer"),
            "status": self._intent_status(raw_status),
            "raw_status": raw_status,
        }
        if raw_status == "requires_action" and payload.get("client_secret"):
            result["client_action"] = {
                "type": "stripe_confirm_payment",
                "client_secret": payload["client_secret"],
            }
        return result

    async def capture(
        self,
        *,
        external_id: str,
        amount_minor: int | None,
        currency: str,
        idempotency_key: str,
    ) -> dict:
        data = {}
        if amount_minor is not None:
            data["amount_to_capture"] = str(amount_minor)
        payload = await self._request(
            "POST",
            f"/payment_intents/{external_id}/capture",
            data=data,
            idempotency_key=idempotency_key,
        )
        raw_status = str(payload.get("status", ""))
        return {
            "external_id": payload.get("id") or external_id,
            "provider_capture_id": payload.get("latest_charge"),
            "status": self._intent_status(raw_status),
            "raw_status": raw_status,
        }

    async def void(
        self,
        *,
        external_id: str,
        idempotency_key: str,
    ) -> dict:
        payload = await self._request(
            "POST",
            f"/payment_intents/{external_id}/cancel",
            data={},
            idempotency_key=idempotency_key,
        )
        raw_status = str(payload.get("status", ""))
        return {
            "external_id": payload.get("id") or external_id,
            "status": self._intent_status(raw_status),
            "raw_status": raw_status,
        }

    async def refund(
        self,
        *,
        external_id: str,
        amount_minor: int,
        currency: str,
        reason: str,
        idempotency_key: str,
    ) -> dict:
        payload = await self._request(
            "POST",
            "/refunds",
            data={
                "payment_intent": external_id,
                "amount": str(amount_minor),
                "reason": "requested_by_customer",
                "metadata[larimia_reason]": reason,
            },
            idempotency_key=idempotency_key,
        )
        raw_status = str(payload.get("status", ""))
        return {
            "external_id": payload.get("id"),
            "status": "SUCCEEDED" if raw_status == "succeeded" else "PENDING",
            "raw_status": raw_status,
        }

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> dict:
        signature = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not signature:
            raise PaymentProviderError("STRIPE_SIGNATURE_REQUIRED")
        timestamp: int | None = None
        supplied: list[str] = []
        for part in signature.split(","):
            key, _, value = part.partition("=")
            if key == "t":
                try:
                    timestamp = int(value)
                except ValueError as exc:
                    raise PaymentProviderError("STRIPE_SIGNATURE_INVALID") from exc
            elif key == "v1" and value:
                supplied.append(value)
        if timestamp is None or not supplied:
            raise PaymentProviderError("STRIPE_SIGNATURE_INVALID")
        if abs(int(time.time()) - timestamp) > self.settings.webhook_replay_window_seconds:
            raise PaymentProviderError("STRIPE_WEBHOOK_REPLAY_WINDOW")
        secret = self.settings.stripe_webhook_secret.get_secret_value().encode()
        expected = hmac.new(
            secret,
            f"{timestamp}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in supplied):
            raise PaymentProviderError("STRIPE_SIGNATURE_INVALID")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PaymentProviderError("STRIPE_PAYLOAD_INVALID") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise PaymentProviderError("STRIPE_PAYLOAD_INVALID")
        return payload

    def translate_webhook(self, payload: dict) -> dict:
        event_type = str(payload.get("type", ""))
        data = payload.get("data", {}).get("object", {})
        if not isinstance(data, dict):
            raise PaymentProviderError("STRIPE_PAYLOAD_INVALID")
        canonical = {
            "payment_intent.amount_capturable_updated": "payment.authorization_succeeded.v1",
            "payment_intent.payment_failed": "payment.authorization_failed.v1",
            "payment_intent.canceled": "payment.authorization_voided.v1",
            "payment_intent.processing": "payment.capture_pending.v1",
            "payment_intent.succeeded": "payment.captured.v1",
            "charge.refund.updated": "payment.refund_pending.v1",
            "charge.refunded": "payment.refunded.v1",
            "charge.dispute.created": "payment.dispute_opened.v1",
            "charge.dispute.closed": "payment.dispute_closed.v1",
        }.get(event_type)
        if canonical is None:
            return {
                "event_type": "payment.provider_event_ignored.v1",
                "data": {"provider_event_type": event_type},
            }
        payment_intent_id = data.get("payment_intent")
        if event_type.startswith("payment_intent."):
            payment_intent_id = data.get("id")
        amount = data.get("amount_refunded") or data.get("amount")
        return {
            "event_type": canonical,
            "data": {
                "external_id": payment_intent_id,
                "provider_capture_id": (data.get("charge") or data.get("id")) if event_type.startswith("charge.") else data.get("latest_charge"),
                "provider_refund_id": data.get("id") if "refund" in event_type else None,
                "amount_minor": amount,
                "currency": str(data.get("currency", "")).upper() or None,
                "raw_status": data.get("status"),
                "provider_event_type": event_type,
            },
        }
