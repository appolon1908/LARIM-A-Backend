# Mission 1 milestone assessment

The active instruction is repository implementation only. PASS means the named gate has local
implementation and test evidence; it never implies Azure certification. FAIL means the original
mission gate is still unmet, including work outside the narrowed scope. No gate is passed by file existence.

| Milestone | Gate | Evidence / remaining work |
|---|---|---|
| M01 Repository and frontend discovery | PASS | Both repositories inspected; contract map and incremental architecture ADR |
| M02 Foundation | PASS | FastAPI, typed settings, real PostgreSQL/Redis, migrations, errors, traces and health; existing synchronous SQLAlchemy retained by ADR |
| M03 Identity/RBAC | PASS | Local login, rotating refresh, signed OIDC validation, issuer-bound users, persisted role permissions and negative tests; actual Entra sign-in awaits cloud validation |
| M04 Profiles/catalog | FAIL | Core profiles, application review, private documents, services and availability work; owned profile/preferences and revocable local device sessions now work; banking onboarding remains |
| M05 Pricing/quotes | PASS | Server pricing, promotion, deterministic minor-unit arithmetic and immutable accepted quote snapshot; unsupported dynamic add-ons explicitly rejected |
| M06 Booking domain | PASS | Canonical state machine, owned idempotent creation, cancellation and tested lifecycle |
| M07 Dispatch/location | PASS | Eligibility, expiring batches, atomic acceptance, Redis positions, pluggable estimated ETA, acceptance history, fairness and market balancing are implemented and tested; live road data is not claimed |
| M08 Jobs/realtime | FAIL | Progression, private evidence, completion and authenticated resumable WebSocket work; snapshotted checklists, independent evidence review and time entries now enforce completion; paid job extras remain |
| M09 Payments/ledger/payouts | PASS | Defined mock gateway, idempotent capture/refund, balanced DB-enforced journal, earnings and simulated payout reservation/completion; no live money claimed |
| M10 Secondary workflows | FAIL | Messaging, reviews, support/disputes/safety and durable in-app delivery work; durable channel adapters/templates/preferences/replay now work; richer safety/review actions remain |
| M11 Operations | FAIL | Protected dispatch, provider review, catalog/pricing, finance, cases and audit work; full breadth of all planned admin models is not complete |
| M12 Quality hardening | FAIL | 73 tests + 3 subtests, local HTTP/WS certification, race/security/retry tests and scans pass; all planned feature contracts, sustained load and external integration validation remain |
| M13 Repository DevOps | PASS | Frozen Docker build, executable CI/CD source and locally compiled Azure foundation/runtime templates; actual CI result recorded in delivery report |
| M14 Azure certification | FAIL | No cloud deployment performed under repository-only scope |

## Checkpoint details

IMPLEMENTED: Persistent customer/provider/operations core, financial and event integrity, local runtime,
private storage, contracts, test automation and deployable infrastructure source.

TESTS: See delivery-report.md and certification.local.json. PostgreSQL 17 and an empty PostgreSQL 18
both pass the suite. Redis is real, not mocked. Cloud and live vendor evidence are absent.

MIGRATIONS: 0003 marketplace, 0004 operations/integrity, 0005 dispatch/issuer, 0006 event delivery; 0007 notifications; 0008 job execution; 0009 ranking explanations; 0010 profiles/devices/sessions.

API CHANGES: 107 canonical operations across 93 /api/v1 paths plus /v1 compatibility aliases.

SECURITY IMPACT: Old success-only handlers are unmounted; persisted ownership, permissions,
JWT verification, command deduplication, balanced immutable journals and private uploads enforce behavior.

KNOWN RISKS: Internal gaps above remain distinct from external credential dependencies. Legacy bookings
require reviewed mapping, rich secondary response schemas need expansion, and live gateway reconciliation
must be implemented before live payment mode is enabled.

NEXT MILESTONE: Close remaining repository feature gates, then separately authorize and validate Azure
staging with actual Entra, storage, Service Bus, monitoring and recovery evidence.
