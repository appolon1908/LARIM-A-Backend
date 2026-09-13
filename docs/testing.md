# Test strategy and evidence

`tests/test_marketplace_domain.py` covers transition legality, exact pricing, score fairness and journal
balance. `tests/test_oidc.py` covers RSA signature, issuer/audience/expiration, required claims,
algorithm rejection and staging configuration. Existing secret-file and legacy state tests remain.

`tests/integration/` uses actual migrated PostgreSQL and Redis for the customer/provider lifecycle,
concurrent acceptance, duplicate commands/refunds, payment decline, ownership, role separation,
provider suspension, offer expiry/recovery, webhook verification/deduplication, refresh rotation,
private documents, append-only audit, DB journal constraints, pricing immutability and worker retry.
No SQLite substitution is used for concurrency or financial tests.

`scripts/certify.py` drives a running HTTP/WebSocket server, including receipt, private evidence,
location, journal/earning visibility and worker/realtime delivery. `docs/certification.local.json`
contains the recorded local result. It explicitly does not certify cloud staging. A staging run
requires HTTPS, explicit --allow-staging, enabled certification, dedicated short-lived identity tokens
and mock payment mode; it cannot silently use real payments.

CI installs the frozen lockfile, checks formatting/Ruff/Mypy/Bandit/dependencies, migrates an empty
PostgreSQL 18/PostGIS database, seeds twice, runs tests, validates OpenAPI, compiles Bicep and builds a
non-root immutable candidate image. Local command success is distinguished from a GitHub run result
in delivery-report.md.
