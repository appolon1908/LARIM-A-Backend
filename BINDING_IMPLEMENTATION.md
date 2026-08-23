# LARIMÍA Marketplace V2 — Binding Implementation Package

## Authority

This package is the implementation baseline for Marketplace V2 review.

Authority order:

1. Backend source code
2. Versioned OpenAPI contract
3. Alembic migrations
4. Automated tests
5. Frontend source code consuming the OpenAPI contract
6. CI / security workflows
7. Architecture and implementation documentation
8. Odoo CRM implementation documentation

If an older architecture draft or scaffold conflicts with this package, this package wins unless explicitly superseded by an approved later version.

## Repository Mapping

Backend GitHub:
`https://github.com/appolon1908-hue/LARIM-A-Backend`

Frontend GitHub:
`https://github.com/appolon1908-hue/LARIM-A-Fornt-end`

Recommended future names:

- `larimia-backend`
- `larimia-frontend`

## Marketplace Ownership

The Python/FastAPI backend is authoritative for:

- customers
- providers
- catalog
- availability
- quotes
- bookings
- dispatch
- visits
- payments
- refunds/disputes
- provider earnings/payouts
- memberships
- safety
- support
- ledger/accounting
- partner booking truth
- integration state

The frontend applications are presentation and interaction layers.

Odoo is CRM/campaign/projection only and must not mutate marketplace truth directly.

## Current Status

This is a PR review candidate, not unrestricted production approval.

Implemented in the current V2 review candidate:

- customer/profile ownership foundations
- provider identity and market foundations
- database-backed catalog/pricing/quotes
- quote-to-booking flow
- booking ownership checks
- booking version/CAS transitions
- persistent idempotency wiring on critical commands
- persistent dispatch offers
- row-lock-based offer acceptance
- provider overlap exclusion constraint
- database-backed visit lifecycle
- payment-intent persistence through provider adapter
- persistent membership/review/support/safety records
- signed/replay-windowed webhook inbox
- authenticated Redis-backed WebSockets
- outbox-to-realtime publisher
- frontend quote/checkout/bookings/SOS/Ops dispatch integration
- CI/security hardening baseline

## Production NO-GO Until

- production Keycloak realm/client deployment is complete
- production payment/payout provider adapters are certified
- routing/maps adapter is complete
- SMS/email/push adapters are complete
- identity/background-check adapters are complete
- object storage and malware scanning are complete
- ledger settlement/refund/dispute/payout/reconciliation is certified
- migration/openapi/frontend contract CI is green in GitHub
- concurrency/load/security tests pass
- backup/restore and DR tests pass
- staging role-by-role E2E tests pass

## Applications

### Customer
Vue / Nuxt / Ionic

### Provider
Vue / Ionic / Capacitor

### Operations
Vue / Nuxt

### Backend
Python / FastAPI / PostgreSQL / PostGIS / Redis / Celery

### CRM
Odoo projection/campaign layer

## Release Convention

Recommended:

```text
marketplace-v2.0.0-rc1
marketplace-v2.0.0-rc2
marketplace-v2.0.0
```
