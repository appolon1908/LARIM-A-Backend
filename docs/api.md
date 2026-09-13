# API contract

Canonical prefix `/api/v1`. The generated, validated contract is `openapi.generated.json`; runtime
OpenAPI is `/openapi.json`. Existing compatible client aliases use `/v1`. Health is outside the prefix.

Dangerous mutations require Idempotency-Key. A key is scoped by authenticated subject and operation;
different payload reuse produces 409. Committed responses are persisted. Money is integer minor units;
dates are UTC ISO-8601; resource IDs are UUIDs. Lists have explicit bounds (maximum 100); bookings and
messages support cursors. Other bounded operations lists need richer pagination before large-scale use.

Errors use `error.code/message/details/trace_id`. Authentication is Bearer JWT; authorization comes
from persisted role permissions and ownership. Request IDs are validated UUIDs or generated afresh.
OpenAPI declares Bearer security through the shared dependency. Quote and booking responses have typed
schemas; secondary response schemas still need stricter typed coverage before claiming complete
contract-first parity across every endpoint.

Core route families: auth, me/addresses/notifications/blocks, catalog/markets, quotes, bookings,
payments/refunds, provider application/profile/services/availability/status/location/offers/jobs/
earnings/payouts/documents, conversations, reviews, support/safety, admin dispatch/provider/catalog/
pricing/finance/payout/refund/audit/identity operations, signed payment webhooks and realtime.
