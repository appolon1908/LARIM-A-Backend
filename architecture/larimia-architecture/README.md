# LARIMÍA Architecture

**Tu bienestar llega a ti.**  
**Wellness, delivered personally.**

LARIMÍA is a bilingual, safety-first marketplace for at-home beauty, grooming, massage, wellness, and personal training services.

This repository is the architecture and implementation authority for the MVP.

## Product Surfaces

1. **LARIMÍA Customer** — discovery, quotes, booking, payments, tracking, messaging, safety, reviews, rebooking.
2. **LARIMÍA Pro** — provider onboarding, credentials, availability, job offers, visit workflow, earnings, payouts, safety.
3. **LARIMÍA Ops** — dispatch, support, safety, finance, provider quality, catalog, pricing, hotels/corporate, compliance.

## Core Stack

### Frontend
- Vue 3 + TypeScript
- Nuxt 4
- Ionic Vue + Capacitor
- Pinia
- Vue I18n
- Vitest
- Playwright
- pnpm workspaces

### Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- PostgreSQL + PostGIS
- Redis
- Celery
- RabbitMQ
- S3-compatible object storage
- OpenTelemetry
- pytest

## Architecture Style

LARIMÍA starts as a **domain-driven modular monolith** with:
- strict module ownership,
- PostgreSQL transactional authority,
- transactional outbox/inbox,
- asynchronous workers,
- adapter-based third-party integrations,
- explicit domain commands instead of generic CRUD.

Microservices are extracted only when scale or team ownership justifies them.

## Repository Set

```text
larimia-frontend/
larimia-backend/
larimia-infrastructure/
larimia-architecture/
```

This repository is `larimia-architecture`.

## Docs

- [System Specification](docs/SPEC-001-LARIMIA.md)
- [System Architecture](docs/ARCHITECTURE.md)
- [Database Design](docs/DATABASE.md)
- [API Design](docs/API.md)
- [Security & Reliability](docs/SECURITY-RELIABILITY.md)
- [Implementation Plan](docs/IMPLEMENTATION.md)
- [ADR-001 Modular Monolith](docs/adr/ADR-001-modular-monolith.md)
- [ADR-002 PostgreSQL Authority](docs/adr/ADR-002-postgresql-authority.md)
- [ADR-003 Transactional Outbox](docs/adr/ADR-003-transactional-outbox.md)

## MVP Launch Order

1. Santo Domingo controlled launch
2. Punta Cana / Bávaro hotel-villa corridor
3. Santiago
4. One U.S. metro through country adapters

## Non-Negotiable Engineering Rules

- No raw card data in LARIMÍA systems.
- No provider double-booking.
- No booking state mutation through generic CRUD.
- No payment or payout without ledger records.
- No privileged operation without audit evidence.
- No external webhook without authentication and deduplication.
- No business-critical state stored only in Redis.
- No production change directly from a developer laptop.
