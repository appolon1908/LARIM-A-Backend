# Payments, ledger and payouts

PaymentGateway defines authorize/capture/cancel/refund. The installed adapter only accepts
`mock_success` or `mock_declined`; readiness reports `payment_mode: mock`. Unrecognized configured
payment modes fail configuration validation. No raw card data is accepted or stored.

Booking locks and durable actor/operation/key records guard dangerous commands. Capture creates one
payment state transition, balanced journal and provider earning. Database deferred triggers reject
unbalanced or mixed-currency journals; foreign keys, positive amounts and immutable audit/journal
triggers add protection beyond Python checks.

Refunds cannot exceed captured remaining amount. Refund journals reverse proportional provider and
platform/tax amounts, and reduce pending earnings. Reserved/paid earnings require an explicit finance
adjustment; the endpoint rejects them rather than creating an unreconciled negative balance.
Payout scheduling locks/reserves pending earnings; completion is explicitly simulated and journals the
provider liability movement. Both actions are audited and idempotent.

Webhook signatures cover timestamp + '.' + raw body; timestamps have a five-minute tolerance. Receipts
are durably deduplicated and marked for reconciliation, not trusted as authority to invent a capture.
A real gateway, banking onboarding, split tax accounts, settlement reconciliation and comprehensive
adjustment workflows remain release gates before any real money movement.
