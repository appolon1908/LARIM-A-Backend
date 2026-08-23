# API Design

## Conventions

- Base prefix: `/v1`
- JSON over HTTPS
- OpenAPI is contract authority
- generated TypeScript client for frontend
- `Idempotency-Key` required for command endpoints
- optimistic concurrency through `If-Match` or explicit aggregate version
- machine-stable error codes
- request/correlation ID on every response

## Customer

```http
GET    /v1/markets/{market}/catalog
POST   /v1/quotes
GET    /v1/availability
POST   /v1/bookings
GET    /v1/bookings/{booking_id}
POST   /v1/bookings/{booking_id}/confirm
POST   /v1/bookings/{booking_id}/reschedule
POST   /v1/bookings/{booking_id}/cancel
POST   /v1/bookings/{booking_id}/arrival-confirmations
POST   /v1/bookings/{booking_id}/complete
POST   /v1/bookings/{booking_id}/tips
POST   /v1/bookings/{booking_id}/reviews
POST   /v1/bookings/{booking_id}/issues
GET    /v1/me/bookings
```

## Provider

```http
POST   /v1/provider-applications
POST   /v1/provider-applications/{id}/documents
GET    /v1/pro/me
PUT    /v1/pro/availability
GET    /v1/pro/offers
POST   /v1/pro/offers/{offer_id}/accept
POST   /v1/pro/offers/{offer_id}/decline
POST   /v1/pro/bookings/{booking_id}/en-route
POST   /v1/pro/bookings/{booking_id}/arrive
POST   /v1/pro/bookings/{booking_id}/start
POST   /v1/pro/bookings/{booking_id}/complete
POST   /v1/pro/bookings/{booking_id}/safety-check
GET    /v1/pro/earnings
GET    /v1/pro/payouts
```

## Operations

```http
GET    /v1/ops/dispatch-board
POST   /v1/ops/bookings/{booking_id}/reassign
POST   /v1/ops/bookings/{booking_id}/override
POST   /v1/ops/refunds
POST   /v1/ops/ledger-adjustments
GET    /v1/ops/reconciliation-breaks
POST   /v1/ops/incidents/{incident_id}/actions
```

## Partner

```http
POST   /v1/partners/bookings
GET    /v1/partners/bookings
GET    /v1/partners/invoices
```

## Webhooks

```http
POST   /v1/webhooks/payments/{provider}
POST   /v1/webhooks/identity/{provider}
POST   /v1/webhooks/messaging/{provider}
```

Webhook flow:

```text
authenticate
deduplicate external event
persist inbox receipt
acknowledge
process asynchronously
commit domain change + outbox
```
