# Implementation Plan

## Phase 0 — Authority

Deliverables:
- trademark/legal review
- corporate/worker model
- insurance
- privacy map
- provider agreements
- safety policy
- cancellation policy
- threat model
- approved ADRs

Exit gate:
- product can legally run a controlled pilot.

## Phase 1 — Platform Foundation

Build:
- frontend monorepo
- backend repository
- infrastructure repository
- environments: dev/staging/prod
- identity
- RBAC
- market configuration
- PostgreSQL/PostGIS
- Redis
- RabbitMQ
- Celery
- object storage
- observability
- CI/CD

Exit gate:
- secure authenticated request flows end-to-end in staging.

## Phase 2 — Transaction Core

Build:
- provider onboarding
- credentials
- catalog
- availability
- quote engine
- booking aggregate
- payment authorization/capture
- ledger
- audit
- inbox/outbox
- notifications

Exit gate:
- deterministic booking/payment/ledger test suite passes.

## Phase 3 — Dispatch

Build:
- provider eligibility
- travel estimates
- ranking
- dispatch waves
- atomic claim
- double-booking exclusion
- Pro offers
- Ops dispatch board
- reassign/recovery

Exit gate:
- concurrency tests demonstrate one provider winner and no provider overlap.

## Phase 4 — Visit & Safety

Build:
- en-route
- geofence arrival
- PIN
- start/complete
- messaging
- SOS
- incident management
- reviews
- support

Exit gate:
- complete controlled service journey passes in staging and pilot environment.

## Phase 5 — Finance Operations

Build:
- provider earnings
- payout batches
- refunds
- disputes
- reconciliation
- finance permissions
- maker/checker controls

Exit gate:
- one booking can be authorized, captured, ledgered, reconciled, and paid out with auditable evidence.

## Phase 6 — Santo Domingo Pilot

Operate:
- limited zones
- limited provider cohort
- manual dispatch oversight
- real customers
- low-volume canary release

Exit gate:
- safety, completion, payment, recovery, and support targets achieved.

## Phase 7 — Scale Features

Build:
- memberships
- favorite provider
- automated late recovery
- hotel/corporate
- negotiated catalog
- kit/inventory
- quality scorecards
- training

## Phase 8 — Market Expansion

Activate:
- Punta Cana/Bávaro
- Santiago
- U.S. payment adapters
- U.S. background check/licensing adapters
- one U.S. metro pilot

## Git Branching

Recommended:

```text
main            protected production branch
develop         optional integration branch
feature/*       short-lived feature branches
fix/*           bug fixes
release/*       release stabilization only if needed
```

Prefer trunk-based development if the team is experienced.

## Pull Request Gate

A merge requires:
- linked issue
- reviewed code
- tests passing
- migrations reviewed
- API changes documented
- no critical security findings
- architecture ADR for significant cross-cutting changes
