# Local development

Prerequisites: Docker Compose; Python 3.13 and uv 0.12.13 for source tooling. `make setup`, `make dev`,
`make seed` starts the private dependencies, migrates, runs API/worker and creates deterministic data.
`.env` is ignored and mode 0600. Existing files are never overwritten by setup. PostgreSQL 18 data is
mounted at `/var/lib/postgresql`; do not attach a PostgreSQL 17 data volume to that image.

The source test suite expects reachable isolated PostgreSQL/PostGIS and Redis, a local JWT key and a
seed password. Set LARIMIA_DATABASE_URL/LARIMIA_REDIS_URL for that test network, then:

```sh
uv sync --frozen --all-extras
uv run --frozen alembic upgrade head
uv run --frozen python scripts/seed.py
uv run --frozen python scripts/seed.py
make lint
make test
```

CI demonstrates host-port service configuration. `docker-compose.mission.yml` is the isolated
PostgreSQL 17/Redis verification overlay used during this mission; it publishes no dependency ports.
A source tooling container can join its network and mount this checkout. Do not run integration tests
against shared staging/customer data: fixtures change provider online/workload state.

`make clean` retains volumes. Never run volume deletion as a routine rollback. Local filesystem
uploads are private; Azure configuration switches storage to the managed-identity Blob adapter.
