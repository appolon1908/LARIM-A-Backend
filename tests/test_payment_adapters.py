import hashlib
import hmac
import json
import time

import pytest

from larimia.config import Settings
from larimia.payments.errors import PaymentProviderError
from larimia.payments.paypal import PayPalPaymentProvider, major_to_minor, minor_to_major
from larimia.payments.stripe import StripePaymentProvider


def test_currency_conversion_is_exact_for_two_decimal_currency():
    assert minor_to_major(12345, "DOP") == "123.45"
    assert major_to_minor("123.45", "DOP") == 12345


@pytest.mark.asyncio
async def test_stripe_webhook_verification_and_translation():
    settings = Settings(
        stripe_webhook_secret="whsec_test",
        stripe_secret_key="sk_test_example",
        stripe_publishable_key="pk_test_example",
        payment_provider_code="stripe",
        payment_provider_codes="stripe",
    )
    adapter = StripePaymentProvider(settings)
    payload = {
        "id": "evt_123",
        "type": "payment_intent.amount_capturable_updated",
        "data": {"object": {"id": "pi_123", "status": "requires_capture", "amount": 1000, "currency": "dop"}},
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(b"whsec_test", f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    verified = await adapter.verify_webhook(headers={"stripe-signature": f"t={timestamp},v1={signature}"}, body=body)
    canonical = adapter.translate_webhook(verified)
    assert canonical["event_type"] == "payment.authorization_succeeded.v1"
    assert canonical["data"]["external_id"] == "pi_123"


@pytest.mark.asyncio
async def test_stripe_rejects_invalid_signature():
    settings = Settings(stripe_webhook_secret="whsec_test", stripe_secret_key="sk_test_example", payment_provider_code="stripe", payment_provider_codes="stripe")
    adapter = StripePaymentProvider(settings)
    with pytest.raises(PaymentProviderError):
        await adapter.verify_webhook(headers={"stripe-signature": f"t={int(time.time())},v1=bad"}, body=b"{}")


def test_paypal_translation_normalizes_capture():
    settings = Settings(paypal_client_id="client", paypal_client_secret="secret", payment_provider_code="paypal", payment_provider_codes="paypal")
    adapter = PayPalPaymentProvider(settings)
    canonical = adapter.translate_webhook({
        "id": "WH-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-1",
            "status": "COMPLETED",
            "amount": {"value": "50.00", "currency_code": "DOP"},
            "supplementary_data": {"related_ids": {"authorization_id": "AUTH-1", "order_id": "ORDER-1"}},
        },
    })
    assert canonical["event_type"] == "payment.captured.v1"
    assert canonical["data"]["external_id"] == "AUTH-1"
    assert canonical["data"]["provider_capture_id"] == "CAPTURE-1"
    assert canonical["data"]["amount_minor"] == 5000
