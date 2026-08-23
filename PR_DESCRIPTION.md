# Marketplace V2 production hardening review

This branch remains a **draft review candidate**. It does not authorize merge, deployment, payments, payouts, automatic assignment, provider self-service, reviews, memberships, partner bookings, or other high-risk capabilities.

## Hardened in this review

- Database-backed customer, provider, catalog, availability, quote, booking, dispatch, visit, payment-intent, membership, review, support and safety foundations.
- Canonical OIDC configuration for `auth.codestra.co` with fixed asymmetric algorithm allowlisting, `kid`, issuer, audience, expiry, issued-at and not-before validation.
- PyJWT/cryptography dependency path instead of the vulnerable `python-jose`/ECDSA chain.
- Server-side capability enforcement. High-risk features fail closed unless explicitly enabled.
- Persistent idempotency with PostgreSQL conflict handling and row locking for concurrent retries.
- Booking optimistic concurrency and provider assignment overlap protection.
- Webhook body limits, replay window, rotating HMAC secrets, raw-body SHA-256, durable dedupe and race-safe inbox insertion.
- Inbox/outbox delivery state, retry scheduling, leasing and stale-worker protection. Migration head is `0004`.
- Database request rollback on unhandled errors.
- Cleaner marketplace services with explicit imports, timezone-aware availability rules and safer quote/dispatch/visit invariants.
- `/v1/health/version` immutable-release identity surface and admin-only `/v1/system/readiness` integration readiness evidence.
- CI checks migration heads, upgrade/downgrade round trip, tests, structural OpenAPI validity and Python compilation.

## Intentionally fail-closed / incomplete

- `payments` and `payouts`: no certified production processor is registered.
- `matching`, `provider_self_service`, `reviews`, `memberships`, `partners`: disabled by default.
- Partner booking endpoints no longer fabricate confirmations; they return `PARTNER_WORKFLOW_NOT_READY` if the capability is explicitly turned on before implementation is complete.
- Visit PINs are hashed but there is not yet a certified secure customer-secret delivery adapter. No raw PIN is emitted to shared events.

## Required before production

- Certified payment and payout adapters plus authorization/capture/refund/dispute/settlement/reconciliation and ledger workflows.
- Routing/geocoding/travel-time, SMS, email, push, identity, background-check, object-storage and malware-scanning adapters.
- Production Keycloak realm/client/session provisioning and end-to-end authorization evidence.
- Durable inbox processors for each provider family, dead-letter/replay operator workflows and webhook provider contract tests.
- File/document domain, quarantine/scanning, signed upload/download and retention policy.
- Rate limits, CSP/CSRF/BFF/session architecture, PII redaction and complete security testing.
- PostgreSQL/PostGIS race tests, role-by-role API tests, Playwright E2E, load/soak and accessibility evidence.
- Metrics/traces/alerts, backup/PITR, isolated restore/DR rehearsal, immutable signed image/SBOM/provenance, staging, canary and rollback certification.

`FINAL_STATUS=PR_REVIEW_CANDIDATE`

`PRODUCTION_STATUS=NO-GO`
