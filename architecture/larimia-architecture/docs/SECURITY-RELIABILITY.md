# Security & Reliability

## Identity

- OIDC Authorization Code + PKCE for interactive clients
- short-lived access tokens
- rotating refresh sessions
- MFA required for providers and staff
- phishing-resistant MFA preferred for privileged staff
- workload identity for machine-to-machine calls

## Authorization

Authorization combines:
- role,
- organization,
- market,
- record relationship,
- action.

A generic `admin=true` permission is prohibited.

## Privileged Actions

Require reason code and audit for:
- manual booking override
- refund
- ledger adjustment
- payout intervention
- account suspension
- safety evidence access
- credential override

## Data Protection

- TLS everywhere
- managed secret store
- encrypted DB and backups
- field protection for highly sensitive PII
- object storage signed URLs
- malware scan on uploads
- retention schedules
- privileged-read audit

## Release Security

Required CI gates:
- unit tests
- integration tests
- contract tests
- migration tests
- SAST
- dependency scanning
- secret scanning
- container scanning
- SBOM generation
- signed image
- end-to-end smoke

## Observability

OpenTelemetry traces:
```text
gateway -> API -> DB -> worker -> external adapter
```

Business metrics:
- quote conversion
- assignment time
- offer acceptance
- late risk
- cancellation
- no-show
- completion
- payment failures
- refunds
- safety SLA
- provider utilization
- reconciliation breaks

## Service Objectives

| Capability | Target |
|---|---:|
| Browse/quote | 99.95% monthly |
| Booking/payment commands | 99.95% monthly |
| Ops dispatch | 99.95% monthly |
| p95 read API | <400 ms excluding third parties |
| p95 command API | <800 ms excluding third parties |
| RPO | <=5 minutes |
| RTO | <=60 minutes |

## Recovery

- PostgreSQL point-in-time recovery
- immutable backup copy in separate failure domain
- quarterly restore test
- replay-safe inbox/outbox
- city/service kill switches
- degraded mode preserving existing bookings when noncritical integrations fail
