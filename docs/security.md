# Security review

Implemented: fixed-algorithm JWT verification, separate issuer bindings, server-owned permissions,
resource ownership, staging OIDC/TLS/CORS guards, bounded request bodies, Redis rate limits, controlled
errors, redacted JSON logs, non-root/read-only containers, private dependency networks, HMAC webhook
verification, durable idempotency, refresh rotation, private document ownership/type/size checks,
immutable journal/audit and transactional outbox. Redis trace statements are reduced to command names;
no payment token/password/auth header is intentionally logged.

Database runtime and migrator credentials are separate in Azure IaC. Runtime workload secret access is
scoped to runtime DB/Redis secrets; migrator identity is separate. Storage uses managed identity and
private containers. Redis public access is disabled behind Private Link; PostgreSQL uses a delegated
private subnet. Vault/Storage/Service Bus still expose authenticated service endpoints; private
endpoints for those services are an optional hardening extension.

Remaining security gates: live Entra/Key Vault/RBAC/network tests; real payment/banking reconciliation;
malware scanning before verification documents can be treated as clean; operational controls for
account recovery/MFA/device/session management; full policy-driven retention; external penetration
review. Uploaded evidence stays QUARANTINED and downloads use attachment/octet-stream. A successful
upload is not a clean-malware verdict. Do not market this source result as a production security audit.

Known compatibility risk: old booking records require explicit migration mapping. No unsafe generic
legacy writer remains mounted. Advanced provider verification is human approval, not a background-check
vendor certification.
