# LARIMÍA Mission 1 delivery report

## 1. Mission status: PARTIAL

A working repository implementation and verified local marketplace runtime are delivered. The original
full Mission 1 is not declared complete. The latest instruction limits work to the backend repository;
no frontend modifications, Azure provisioning or production release were performed. Internal feature
gaps are listed in the milestone assessment and are not misclassified as missing credentials.

## 2. Staging endpoint

Azure: not deployed. Local verification endpoint on the execution host: http://127.0.0.1:18092/api/v1.
Fresh clones use http://localhost:8000/api/v1 with `make setup`, `make dev`, `make seed`.
This loopback address is not a public staging URL.

## 3. Architecture delivered

Python 3.13 FastAPI modular monolith, synchronous SQLAlchemy retained incrementally, PostgreSQL/PostGIS,
Redis location/presence/rate limiting, durable transactional outbox and leased cloud event delivery.
Identity and permissions are database-bound. Payment behavior uses an explicit deterministic gateway;
ledger integrity is enforced both in application logic and PostgreSQL. Azure managed-identity storage
and Service Bus adapters coexist with local private storage and PostgreSQL-driven notifications.

## 4. Milestones

See [M01–M14 matrix](milestones.md). Several full-scope gates remain FAIL; this is an implementation
review candidate, not a certified production release.

## 5. Test report

- Unit, integration, contract and API E2E: 68 passed plus 3 subtests on PostgreSQL 17 and separately on
  an empty PostgreSQL 18/PostGIS database with Redis. Two upstream test-client deprecation warnings remain.
- HTTP/WebSocket container certification: all 27 checks PASS; [step-by-step evidence](certification.local.json).
- Restricted runtime-role verification: all 68 tests plus 3 subtests pass using `larimia_app`,
  provisioned by the migration script without superuser/schema-creation or journal-update rights.
- Local read baseline: 50 sequential catalog reads, median 3.18 ms / p95 5.14 ms; this is not a
  sustained or cloud-load benchmark.
- API/worker restart: previous booking receipt and captured payment remained readable; readiness PASS.
- Ruff and format checks: PASS. Mypy: PASS across 98 source files. Bandit: zero medium/high findings.
- Frozen dependency audit: no known public-package vulnerabilities; the private project itself is not
  on PyPI and is assessed through source review/Bandit rather than registry lookup.
- Secret scan: candidate tracked-file scan PASS; ignored local .env is excluded. The PR workflow also
  scans Git history; its metadata read permission was corrected after the first remote run.
- OpenAPI validation, unique operation IDs and bearer declaration checks: PASS.
- Docker build/non-root runtime: PASS. Bicep foundation/runtime compilation and workflow lint: PASS.
- GitHub backend CI: [PASS on source commit 73b1b8e](https://github.com/appolon1908-hue/LARIM-A-Backend/actions/runs/34750238438),
  including the container HTTP/WebSocket scenario. Current checks are attached to
  [draft PR #9](https://github.com/appolon1908-hue/LARIM-A-Backend/pull/9).
- Cloud smoke/CD, live Entra and external telemetry export: not executed.

## 6. Infrastructure report

Repository contains Docker Compose and Bicep for resource group, VNet, ACR, Container Apps environment,
API/worker/migration job, PostgreSQL, private Managed Redis, Key Vault, private Blob storage, Service Bus,
managed identities/RBAC, Log Analytics and Application Insights. No Azure resources were provisioned.
The manual deployment workflow gates promotion on source checks and successful migrations, then runs
health and dedicated mock-payment certification. It has not been triggered.

## 7. Database report

Alembic revision: **0009**. Empty PostgreSQL 18 database → head → seed twice → complete test suite PASS.
Existing 0001/0002 tables are preserved. New marketplace rows have explicit quote provenance; legacy
booking rows are available only to authorized operations pending a reviewed mapping. Forward-only
financial migrations reject automatic destructive downgrade. Application rollback requires an image
compatible with the expanded schema; restore into a separate database before any data cutover.

## 8. API report

[OpenAPI](../openapi.generated.json): 100 canonical operations across 89 `/api/v1` paths, compatibility
aliases under `/v1`, health and authenticated WebSocket gateway. Typed booking/quote schemas protect
critical frontend flows; broader secondary response schemas still need expansion.

## 9. Local E2E certification

The JSON evidence records every step: login, catalog/address, quote/booking, authorization, dispatch,
provider acceptance, assignment, en route/location/arrival, job start/evidence/completion, capture,
receipt, earning, review, admin booking/payment/journal visibility, balanced ledger, audit and worker/
WebSocket delivery. All pass locally. No claim is made that these passed against Azure staging.

## 10. Remaining external dependencies

Azure subscription/federation and reviewed deployment parameters; Entra customer/provider and workforce
app registrations plus dedicated test principals; real vendor contracts and credentials for payments,
maps, push/email/SMS; actual cloud monitoring and recovery validation. See [staging setup](staging.md).
Missing repository behavior is separately tracked in [milestones](milestones.md).

## 11. Frontend handoff

Mission 2 must use [frontend contract map](frontend-contract-map.md),
[exact integration changes](frontend-migration-contract.md), [OpenAPI](../openapi.generated.json),
[realtime protocol](realtime.md) and README demo identity instructions. Passwords are generated in the
ignored local `.env`; no universal demo password is committed. Cloud API base remains unset.


## Implementation follow-up

Migrations 0007–0009 add durable external notification templates/preferences/leases/replay, a separately
running notification worker and explicit SIMULATED versus gateway ACCEPTED states; immutable job-policy
snapshots, checklist evidence review and server time entries enforced before capture; and shared dispatch
ranking using cached positions, estimated ETA, historical acceptance/fairness and market-balance signals.

The local HTTP/WebSocket scenario now also requires an asynchronous notification receipt (27 checks).
The full suite includes a standalone worker subprocess regression after catching an API-only metadata
import dependency. CI uses three application containers for API, outbox worker and notification worker.
Current follow-up CI results are attached to PR #9; the earlier linked run remains historical evidence.
See notifications.md, job-execution.md and the frontend migration contract for integration details.
