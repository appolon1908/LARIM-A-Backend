# LARIMÍA Backend — Production Baseline

FastAPI/Python backend for the LARIMÍA Customer, Pro and Operations platforms.

## Included

- modular domain structure
- PostgreSQL/PostGIS persistence
- Alembic baseline migration
- Redis + RabbitMQ + Celery runtime
- Customer, Provider, Ops, Partner and integration API surfaces
- WebSocket routes for booking state, dispatch and provider offers
- booking state machine
- idempotent command contract
- audit/outbox/inbox models
- ledger models
- role-based authorization scaffold
- Docker Compose
- Kubernetes deployment starter
- GitHub CI/security workflows
- production-gate documentation

## Important

`X-Demo-Subject` / `X-Demo-Roles` are a **development-only authentication shim**. Production launch requires a real OIDC provider and verified JWT claims.

External payment, identity, background-check, routing, SMS/email/push providers are intentionally adapter boundaries. Real provider credentials and market certification are deployment work, not safe defaults to hard-code into a repository.

## Start

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
```

Then visit:
- API docs: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`
- live: `http://localhost:8000/v1/health/live`
- ready: `http://localhost:8000/v1/health/ready`

See `docs/API-MATRIX.md` and `docs/PRODUCTION-GATES.md`.
