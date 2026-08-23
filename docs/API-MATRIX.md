# LARIMÍA API Matrix

## Customer
- `GET /v1/markets`
- `GET /v1/catalog`
- `GET /v1/availability`
- `POST /v1/quotes`
- `POST /v1/bookings`
- `GET /v1/bookings/{id}`
- `POST /v1/bookings/{id}/quote`
- `POST /v1/bookings/{id}/confirm`
- `POST /v1/bookings/{id}/cancel`
- `POST /v1/payments/authorize`
- `POST /v1/reviews`
- `POST /v1/support/cases`
- `GET /v1/memberships/plans`
- `POST /v1/memberships/subscriptions`
- `WS /v1/ws/bookings/{id}`

## Provider
- `POST /v1/providers/applications`
- `GET /v1/providers/me`
- `PUT /v1/providers/me/availability`
- `GET /v1/providers/me/earnings`
- `GET /v1/providers/me/payouts`
- `GET /v1/dispatch/offers`
- `POST /v1/dispatch/offers/{id}/accept`
- `POST /v1/dispatch/offers/{id}/decline`
- `POST /v1/visits/{booking}/en-route`
- `POST /v1/visits/{booking}/arrive`
- `POST /v1/visits/{booking}/start`
- `POST /v1/visits/{booking}/complete`
- `WS /v1/ws/providers/{provider_id}/offers`

## Operations
- `GET /v1/dispatch/ops/board`
- `POST /v1/dispatch/ops/bookings/{id}/reassign`
- `POST /v1/bookings/{id}/start-matching`
- `GET /v1/safety/ops/incidents`
- `POST /v1/safety/ops/incidents/{id}/actions`
- `GET /v1/support/ops/cases`
- `POST /v1/support/ops/cases/{id}/actions`
- `GET /v1/finance/reconciliation-breaks`
- `POST /v1/finance/ledger-adjustments`
- `GET /v1/finance/payout-batches`
- `POST /v1/providers/{provider_id}/status`
- `POST /v1/catalog`
- `WS /v1/ws/ops/dispatch`

## Partners
- `POST /v1/partners/bookings`
- `GET /v1/partners/bookings`
- `GET /v1/partners/invoices`

## Integrations
- `POST /v1/webhooks/payments/{provider}`
- `POST /v1/webhooks/identity/{provider}`

## Health
- `GET /v1/health/live`
- `GET /v1/health/ready`
- `/docs` OpenAPI UI
- `/openapi.json` machine contract
