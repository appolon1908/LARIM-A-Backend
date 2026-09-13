# Operations runbook

1. Verify `/health/live` then `/health/ready`; readiness includes DB connectivity, exact migration
   revision and Redis. It also identifies mock payment mode and build version.
2. Inspect JSON logs by request/trace ID; never paste token-bearing headers, environment dumps or
   credential files into tickets. OTLP export is asynchronous and bounded.
3. Inspect pending outbox/event deliveries and worker logs. Restarting a worker preserves PostgreSQL
   state. A leased external event becomes retryable after its lease; duplicates use stable event IDs.
4. Inspect `/admin/events/dlq` and replay only with an authorized integration operator. Replays are
   audited, use the same logical event and cannot bypass booking/financial state checks.
5. Inspect `/finance/reconciliation-breaks` before payouts. Do not repair journal history with UPDATE;
   introduce reviewed compensating transactions. Paid/reserved earning refunds are intentionally blocked.
6. Inspect `/admin/dispatch` recovery queue for NO_PROVIDER_FOUND and unavailable/suspended providers.
   Do not bypass approval or manually update a booking status in SQL.

Migration is forward-only once money/events exist. For application rollback select the prior immutable
image and verify it is compatible with the expanded schema. For database recovery restore into a new
isolated database, compare journal totals, replay/reconcile events, then cut over. Do not downgrade or
delete audit/ledger tables automatically. A real cloud backup-restore rehearsal remains unexecuted.

Local `docker compose restart api worker` is safe for persisted bookings. After redeploy, recheck
readiness, receipt visibility, outbox drain and reconnect delivery. Restore scripts and cloud retention
must be exercised with the actual subscription before staging certification can be signed.
