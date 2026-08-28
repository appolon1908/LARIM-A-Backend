import asyncio
import json
import time
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP

import httpx

from larimia.config import Settings
from larimia.payments.errors import PaymentProviderError


_ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
_THREE_DECIMAL = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = asyncio.Lock()


def _exponent(currency: str) -> int:
    code = currency.upper()
    if code in _ZERO_DECIMAL:
        return 0
    if code in _THREE_DECIMAL:
        return 3
    return 2


def minor_to_major(amount_minor: int, currency: str) -> str:
    exponent = _exponent(currency)
    value = Decimal(amount_minor) / (Decimal(10) ** exponent)
    return f"{value:.{exponent}f}"


def major_to_minor(value: str | int | float | Decimal | None, currency: str) -> int | None:
    if value is None:
        return None
    exponent = _exponent(currency)
    decimal_value = Decimal(str(value)) * (Decimal(10) ** exponent)
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PayPalPaymentProvider:
    code = "paypal"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_base = settings.paypal_api_base.rstrip("/")

    async def _access_token(self) -> str:
        cache_key = f"{self.api_base}:{self.settings.paypal_client_id}"
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > time.monotonic() + 30:
            return cached[0]
        async with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(cache_key)
            if cached and cached[1] > time.monotonic() + 30:
                return cached[0]
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.payment_http_timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        f"{self.api_base}/v1/oauth2/token",
                        data={"grant_type": "client_credentials"},
                        auth=(
                            self.settings.paypal_client_id,
                            self.settings.paypal_client_secret.get_secret_value(),
                        ),
                        headers={"Accept": "application/json"},
                    )
            except httpx.TimeoutException as exc:
                raise PaymentProviderError("PAYPAL_TIMEOUT", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise PaymentProviderError("PAYPAL_NETWORK_ERROR", retryable=True) from exc
            if response.status_code >= 400:
                raise PaymentProviderError(
                    "PAYPAL_AUTHENTICATION_FAILED",
                    retryable=response.status_code >= 500,
                    http_status=response.status_code,
                )
            payload = response.json()
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not token:
                raise PaymentProviderError("PAYPAL_AUTHENTICATION_RESPONSE_INVALID")
            expires_in = int(payload.get("expires_in", 300))
            _TOKEN_CACHE[cache_key] = (str(token), time.monotonic() + expires_in)
            return str(token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        token = await self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.payment_http_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.api_base}{path}",
                    json=json_body,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise PaymentProviderError("PAYPAL_TIMEOUT", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PAYPAL_NETWORK_ERROR", retryable=True) from exc
        try:
            payload = response.json() if response.content else {}
        except ValueError as exc:
            raise PaymentProviderError(
                "PAYPAL_INVALID_RESPONSE",
                retryable=response.status_code >= 500,
                http_status=response.status_code,
            ) from exc
        if response.status_code >= 400:
            name = payload.get("name") if isinstance(payload, dict) else None
            details = payload.get("details") if isinstance(payload, dict) else None
            issue = None
            if isinstance(details, list) and details and isinstance(details[0], dict):
                issue = details[0].get("issue")
            raise PaymentProviderError(
                f"PAYPAL_{str(issue or name or 'REQUEST_FAILED').upper()}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                http_status=response.status_code,
            )
        if not isinstance(payload, dict):
            raise PaymentProviderError("PAYPAL_INVALID_RESPONSE")
        return payload

    async def create_checkout(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict:
        payload = await self._request(
            "POST",
            "/v2/checkout/orders",
            idempotency_key=idempotency_key,
            json_body={
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "reference_id": str(reference["booking_id"]),
                        "custom_id": str(reference["booking_id"]),
                        "invoice_id": str(reference.get("booking_number", reference["booking_id"])),
                        "description": "LARIMIA service booking",
                        "amount": {
                            "currency_code": currency.upper(),
                            "value": minor_to_major(amount_minor, currency),
                        },
                    }
                ],
                "application_context": {
                    "return_url": self.settings.paypal_return_url,
                    "cancel_url": self.settings.paypal_cancel_url,
                    "user_action": "CONTINUE",
                    "shipping_preference": "NO_SHIPPING",
                },
            },
        )
        links = payload.get("links") or []
        approve_url = next(
            (
                item.get("href")
                for item in links
                if isinstance(item, dict) and item.get("rel") in {"approve", "payer-action"}
            ),
            None,
        )
        if not payload.get("id") or not approve_url:
            raise PaymentProviderError("PAYPAL_ORDER_RESPONSE_INVALID")
        return {
            "external_order_id": payload["id"],
            "approve_url": approve_url,
            "status": str(payload.get("status", "CREATED")),
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
        payload = await self._request(
            "POST",
            f"/v2/checkout/orders/{token}/authorize",
            json_body={},
            idempotency_key=idempotency_key,
        )
        authorizations = []
        for unit in payload.get("purchase_units") or []:
            payments = unit.get("payments") if isinstance(unit, dict) else None
            if isinstance(payments, dict):
                authorizations.extend(payments.get("authorizations") or [])
        authorization = authorizations[0] if authorizations else None
        if not isinstance(authorization, dict) or not authorization.get("id"):
            raise PaymentProviderError("PAYPAL_AUTHORIZATION_RESPONSE_INVALID")
        raw_status = str(authorization.get("status", ""))
        return {
            "external_id": authorization["id"],
            "provider_order_id": payload.get("id") or token,
            "provider_authorization_id": authorization["id"],
            "status": "AUTHORIZED" if raw_status in {"CREATED", "CAPTURED"} else "AUTHORIZATION_PENDING",
            "raw_status": raw_status,
        }

    async def capture(
        self,
        *,
        external_id: str,
        amount_minor: int | None,
        currency: str,
        idempotency_key: str,
    ) -> dict:
        body: dict = {"final_capture": True}
        if amount_minor is not None:
            body["amount"] = {
                "currency_code": currency.upper(),
                "value": minor_to_major(amount_minor, currency),
            }
        payload = await self._request(
            "POST",
            f"/v2/payments/authorizations/{external_id}/capture",
            json_body=body,
            idempotency_key=idempotency_key,
        )
        raw_status = str(payload.get("status", ""))
        return {
            "external_id": external_id,
            "provider_capture_id": payload.get("id"),
            "status": "CAPTURED" if raw_status == "COMPLETED" else "CAPTURE_PENDING",
            "raw_status": raw_status,
        }

    async def void(
        self,
        *,
        external_id: str,
        idempotency_key: str,
    ) -> dict:
        await self._request(
            "POST",
            f"/v2/payments/authorizations/{external_id}/void",
            json_body={},
            idempotency_key=idempotency_key,
        )
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
        payload = await self._request(
            "POST",
            f"/v2/payments/captures/{external_id}/refund",
            json_body={
                "amount": {
                    "currency_code": currency.upper(),
                    "value": minor_to_major(amount_minor, currency),
                },
                "note_to_payer": reason[:255],
            },
            idempotency_key=idempotency_key,
        )
        raw_status = str(payload.get("status", ""))
        return {
            "external_id": payload.get("id"),
            "status": "SUCCEEDED" if raw_status == "COMPLETED" else "PENDING",
            "raw_status": raw_status,
        }

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> dict:
        required = {
            "auth_algo": headers.get("paypal-auth-algo") or headers.get("PAYPAL-AUTH-ALGO"),
            "cert_url": headers.get("paypal-cert-url") or headers.get("PAYPAL-CERT-URL"),
            "transmission_id": headers.get("paypal-transmission-id") or headers.get("PAYPAL-TRANSMISSION-ID"),
            "transmission_sig": headers.get("paypal-transmission-sig") or headers.get("PAYPAL-TRANSMISSION-SIG"),
            "transmission_time": headers.get("paypal-transmission-time") or headers.get("PAYPAL-TRANSMISSION-TIME"),
        }
        if any(not value for value in required.values()):
            raise PaymentProviderError("PAYPAL_WEBHOOK_HEADERS_REQUIRED")
        try:
            event = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PaymentProviderError("PAYPAL_PAYLOAD_INVALID") from exc
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise PaymentProviderError("PAYPAL_PAYLOAD_INVALID")
        verification = await self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json_body={
                **required,
                "webhook_id": self.settings.paypal_webhook_id,
                "webhook_event": event,
            },
        )
        if verification.get("verification_status") != "SUCCESS":
            raise PaymentProviderError("PAYPAL_SIGNATURE_INVALID")
        return event

    def translate_webhook(self, payload: dict) -> dict:
        event_type = str(payload.get("event_type", ""))
        resource = payload.get("resource") or {}
        if not isinstance(resource, dict):
            raise PaymentProviderError("PAYPAL_PAYLOAD_INVALID")
        canonical = {
            "PAYMENT.AUTHORIZATION.CREATED": "payment.authorization_succeeded.v1",
            "PAYMENT.AUTHORIZATION.VOIDED": "payment.authorization_voided.v1",
            "PAYMENT.CAPTURE.PENDING": "payment.capture_pending.v1",
            "PAYMENT.CAPTURE.COMPLETED": "payment.captured.v1",
            "PAYMENT.CAPTURE.DENIED": "payment.capture_failed.v1",
            "PAYMENT.CAPTURE.REFUNDED": "payment.refunded.v1",
            "CUSTOMER.DISPUTE.CREATED": "payment.dispute_opened.v1",
            "CUSTOMER.DISPUTE.RESOLVED": "payment.dispute_closed.v1",
        }.get(event_type)
        if canonical is None:
            return {
                "event_type": "payment.provider_event_ignored.v1",
                "data": {"provider_event_type": event_type},
            }
        related = resource.get("supplementary_data", {}).get("related_ids", {})
        if not isinstance(related, dict):
            related = {}
        amount = resource.get("amount") or resource.get("seller_payable_breakdown", {}).get("gross_amount") or {}
        if not isinstance(amount, dict):
            amount = {}
        currency = str(amount.get("currency_code", "")).upper()
        authorization_id = related.get("authorization_id")
        if event_type.startswith("PAYMENT.AUTHORIZATION."):
            authorization_id = resource.get("id")
        capture_id = resource.get("id") if event_type.startswith("PAYMENT.CAPTURE.") else related.get("capture_id")
        return {
            "event_type": canonical,
            "data": {
                "external_id": authorization_id,
                "provider_order_id": related.get("order_id"),
                "provider_capture_id": capture_id,
                "provider_refund_id": resource.get("id") if event_type == "PAYMENT.CAPTURE.REFUNDED" else None,
                "amount_minor": major_to_minor(amount.get("value"), currency) if currency else None,
                "currency": currency or None,
                "raw_status": resource.get("status"),
                "provider_event_type": event_type,
            },
        }
