# LARIMÍA Marketplace V2 implementation execution

This branch is the consolidated implementation line created from the hardened Marketplace V2 review head.

## Authority

- LARIMÍA PostgreSQL is authoritative for marketplace, booking, dispatch, visit, safety, payment, ledger, membership and partner truth.
- Redis is cache, realtime and lease infrastructure only.
- RabbitMQ/Celery carries durable asynchronous work.
- Odoo receives approved CRM projections and never writes directly to LARIMÍA storage.
- Codestra Middleware remains the cross-system write boundary for Odoo, n8n, Klyrow and Telnexa.

## Dependency order

1. Repository and API contract convergence.
2. Identity, record-level authorization and service identities.
3. Capacity holds and payment-safe booking confirmation.
4. Matching, dispatch and visit workflow.
5. Durable inbox/outbox and replayable realtime delivery.
6. Ledger, reconciliation, refunds and payouts.
7. Customer, provider, operations and partner portals.
8. Integrations, observability, restore/DR and release certification.

## Release policy

High-risk capabilities remain disabled until the corresponding adapter, authorization, reconciliation, monitoring, rollback and operator evidence exist. A green CI run is necessary but never sufficient for production activation.
