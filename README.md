# LARIMÍA marketplace backend

Python 3.13 / FastAPI modular monolith with PostgreSQL/PostGIS, Redis, durable outbox processing,
identity and permission checks, server-priced quotes, booking/dispatch/job workflows, mock payment
capture/refunds, balanced journals, payouts, private documents, messaging, reviews and operations APIs.

This repository contains a working **local marketplace implementation**, not a certification of live
payments or Azure staging. The frontend reference was inspected read-only. See
[delivery report](docs/delivery-report.md) for evidence and remaining gates.

## Start a fresh local environment

```sh
make setup       # writes random local credentials to ignored .env, permissions 0600
make dev         # builds API/worker; starts private PostgreSQL 18/PostGIS + Redis; migrates first
make seed        # deterministic identities, services, bookings, promotion, journal and payout
```

API: http://localhost:8000/api/v1 · OpenAPI: http://localhost:8000/openapi.json
Health: `/health/live`, `/health/ready`. Compatible client paths remain under `/v1`.
Database and Redis have no host port publications. API binds host loopback only.

Demo identities: `customer1`, `customer2`, `provider1` through `provider5`, `admin`, `dispatcher`,
`support`, `finance`, all at `@demo.larimia.test`. The generated `.env` contains the local
`LARIMIA_SEED_PASSWORD`. Never reuse demo credentials in a public environment.
`provider5` is pending; other providers are approved but offline until an authenticated update.

```sh
# Installed source workflow (Python 3.13; point DB/Redis settings at isolated dependencies):
uv sync --frozen --all-extras
make lint
make test
make openapi
# Against running Compose, execute the HTTP certification inside the API container:
docker compose exec api python scripts/certify.py --base-url http://localhost:8000
```

See [local development](docs/local-development.md) for host and container test commands.
`make clean` stops containers without deleting durable volumes.

## Contracts and release

- [Frontend contract map](docs/frontend-contract-map.md)
- [Mission 2 migration contract](docs/frontend-migration-contract.md)
- [Generated OpenAPI](openapi.generated.json)
- [Architecture](docs/architecture.md), [domain model](docs/domain-model.md)
- [Security](docs/security.md), [operations](docs/operations-runbook.md)
- [Azure source and staging gates](docs/staging.md)

Cloud deployment is not executed by this repository implementation task. Bicep creates the foundation;
the manual staging workflow requires Azure federation, reviewed parameters, a passing source gate and
short-lived dedicated certification identities. Mock payment mode is explicitly reported in readiness.
