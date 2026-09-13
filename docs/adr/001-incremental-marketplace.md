# ADR 001 — Incremental marketplace implementation

Preserve FastAPI, SQLAlchemy models, minor-unit integer money, existing migrations and secret-file delivery. Build application services and transactional persistence behind canonical /api/v1 routes; retain compatible /v1 paths. Retire fabricated-success route handlers from mounted routing as their capabilities are implemented. Unsupported capabilities must not report success.

The repository currently uses synchronous SQLAlchemy/psycopg. Preserve bounded synchronous request services initially, which FastAPI runs in its thread pool. An async driver migration is outstanding; do not claim the async target achieved. Domain modules remain within one deployment. A local durable outbox worker substitutes for unavailable event vendors, never for financial correctness. No Kubernetes or cloud mutation is required for this repository-only instruction.

PostgreSQL row locks serialize booking/offer and payment operations. Transaction-scoped advisory locks serialize idempotency keys, with a unique persisted response record in the same transaction. Financial journal writes are balanced and immutable. External gateway effects require their own stable operation reference and reconciliation; mock gateway is deterministic and explicitly identified.
