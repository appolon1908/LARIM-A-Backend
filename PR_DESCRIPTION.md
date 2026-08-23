# Marketplace core: persistence, authorization, concurrency, webhook and realtime hardening

## Addresses production review blockers

- Replaces hard-coded catalog, availability, provider application, quote, booking, dispatch, visit, payment-intent, membership, review, support and safety write paths with database-backed behavior.
- Binds customers/providers to OIDC `issuer + subject`.
- Enforces booking ownership and market scopes.
- Uses persistent idempotency records on high-value commands.
- Adds `If-Match` / version CAS for booking state changes.
- Adds row locks for quote consumption and offer acceptance.
- Adds PostgreSQL exclusion constraint preventing overlapping active provider assignments.
- Adds signed, replay-windowed webhook ingestion with durable inbox dedupe.
- Adds authenticated Redis-backed WebSocket channels and an outbox publisher.
- Makes sandbox payments fail closed in production.
- Makes CI run lint, migrations, tests, OpenAPI drift and migration round-trip.

## Deliberate follow-ups before public production

- Real payment/payout processor implementation and certification.
- Full ledger settlement/refund/dispute/payout/reconciliation workflow.
- Production Keycloak realm/client provisioning at `auth.codestra.co`.
- Routing, SMS/email/push, identity, background-check, object-storage/malware adapters.
- Complete security/load/restore/staging E2E evidence.
