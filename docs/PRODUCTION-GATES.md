# Production Gates

This repository is not considered production-approved until all gates below are passed with real configured providers.

## Identity
- OIDC/JWT verification replaces `X-Demo-*` development headers.
- MFA enforced for provider and staff roles.
- record-level authorization tests pass.

## Payments
- payment adapter selected and certified for each market.
- webhook signatures verified.
- duplicate webhook tests pass.
- capture/refund/dispute/reconciliation tests pass.

## Dispatch
- provider overlap exclusion constraint implemented for assignments.
- atomic offer claim tested with concurrent requests.
- map/routing adapter connected.
- failover/recovery exercised.

## Safety
- SOS routes to staffed response workflow.
- incident severity and escalation policy approved.
- location retention and privacy rules approved.

## Infrastructure
- TLS/WAF/managed secrets configured.
- production DB is HA and backed up.
- point-in-time restore tested.
- RPO/RTO exercise completed.
- alerts and on-call rotation active.

## Security
- SAST/SCA/secret/container scanning green.
- pentest complete for launch surface.
- no unresolved critical vulnerabilities.
- SBOM produced for every release.

## Business
- worker model, insurance, provider requirements, tax and privacy approved per market.
- controlled real booking completes end-to-end before unrestricted launch.
