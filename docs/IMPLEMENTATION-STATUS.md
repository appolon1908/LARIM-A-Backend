# Implementation Status

## Implemented in this review candidate

- modular FastAPI application structure
- PostgreSQL/PostGIS runtime
- Alembic migration chain
- request IDs and standard domain error shape
- OIDC/JWKS verification path
- fail-closed production auth configuration
- RBAC role model
- capability registry/gates foundation
- command context type
- persistent idempotency schema/service foundation
- optimistic booking version
- explicit booking state machine
- audit records
- transactional outbox schema
- durable inbox schema
- provider-neutral integration interfaces
- integration readiness/control-plane table
- WebSocket channels for booking, provider offers, and Ops dispatch
- customer/provider/ops/partner API surfaces
- payment/ledger/payout foundations
- customer, pro and ops frontend portals
- Docker Compose
- Kubernetes starter
- CI and security workflow starters

## Not truthfully production-complete without environment/vendor work

- real OIDC tenant/client configuration and end-to-end auth certification
- production payment/payout adapters and webhook signatures
- maps/routing adapter
- SMS/email/push provider adapters
- identity/background-check adapters
- S3/object scanning adapters
- complete relational schemas for every domain
- database-backed dispatch offers/assignments with overlap exclusion
- real pricing/tax policy configuration
- finance reconciliation against live settlement files
- mobile push and native permission flows
- full record-level authorization across every query
- load, penetration, chaos, restore and disaster-recovery evidence
- market legal/compliance approvals

The repository should be reviewed as a **production review candidate**, not represented as an unrestricted production launch.
