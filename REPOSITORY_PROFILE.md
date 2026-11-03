# Repository Profile — `LARIM-A-Backend`

## Identity

- **Repository:** `appolon1908-hue/LARIM-A-Backend`
- **Category:** Product backend — LARIMÍA marketplace
- **Visibility:** `private`
- **Default branch:** `main`
- **Authority:** Primary LARIMÍA backend authority
- **Status:** FastAPI/PostGIS baseline with demo authentication still requiring replacement before production.

## Purpose

Provides the marketplace backend for customer bookings, provider operations, dispatch, visits, payments, partner integrations, realtime events, audit, and worker processing.

## Owns

- LARIMÍA APIs, persistence, booking and dispatch state machines
- Tenant authorization, idempotency, audit, outbox/inbox, ledger, WebSockets, and workers
- Payment, identity, background-check, routing, and communications adapter boundaries

## Does not own

- Frontend presentation
- Production use of demo subject/role headers
- Hard-coded external-provider credentials or unreviewed live effects

## Key integrations

- `LARIM-A-Fornt-end`
- OIDC/Keycloak
- PostgreSQL/PostGIS, Redis, RabbitMQ, and Celery
- Payment, identity, safety, maps, email, SMS, and push adapters

## Current priorities

1. Replace demo authentication with fail-closed JWT validation
2. Complete authorization, idempotency, payment, webhook, and state-machine controls
3. Prove worker, inbox/outbox, WebSocket, and recovery behavior
4. Finish immutable deployment, backup/restore, rollback, and production gates

## Governance and safety

- Promotion model: `feature/docs/fix/security/upgrade -> development -> test -> staging -> production -> main`.
- Use pull requests and exact-head/merge-result validation; source merge never authorizes marketplace effects.
- Never commit credentials, customer/provider PII, payment data, background-check data, or database dumps.
- Production artifacts and migrations must be immutable, traceable, and reversible.
- This document does not book, dispatch, charge, provision, notify, or activate production.

## Account-wide catalog

See `appolon1908-hue/documentaions/REPOSITORY_CATALOG.md`.
