# ADR 002 — Isolate external notifications and snapshot job requirements

Status: accepted.

External messaging must not block marketplace transactions. Keep the existing in-app outbox consumer
and add a separately deployed, leased notification consumer. Render immutable delivery snapshots in a
transaction, then perform network I/O after committing the lease. Use explicit SIMULATED/ACCEPTED states
to avoid confusing local mocks or provider acknowledgement with confirmed recipient delivery.

Service completion requirements affect both provider obligations and capture eligibility. Snapshot the
versioned policy when creating the quote, retain it at acceptance and enforce it before capture. Use
server time and a booking-first lock order for checklist changes, independent evidence reviews and
completion. Do not backfill new obligations onto existing accepted bookings.

Dispatch scoring remains centralized and gains persisted explanations, historical acceptance/fairness
signals and an injectable travel estimator. Redis positions improve estimates; durable service-area
coordinates remain the fallback. Local travel estimates are labelled and never advertised as live traffic.

Consequences: three additive migrations, one extra worker, opt-in external channel configuration,
new provider/admin APIs and additional frontend integration work. Vendor deduplication and actual
verified destination resolution are explicit relay responsibilities. Paid job extras, full onboarding
and cloud certification remain separate gates.
