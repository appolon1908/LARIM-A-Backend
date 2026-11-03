# Authentication

Local mode uses password hashes (scrypt, random per-user salt) and HS256 JWTs with an externally supplied
random key. Registering a user grants only customer role. The provider application flow adds product
provider membership but never approval. Login returns a 30-minute access token and a seven-day refresh
secret. Refresh secrets are stored hashed, locked during rotation and revoked on use/logout. Access
JWTs expire naturally after logout; account disablement is checked on each request.

Staging/production require OIDC with HTTPS issuer/JWKS, explicit audience and RS256. Signature,
issuer, audience, expiration and subject are checked. JWKS caches expire in five-minute buckets and
refresh on an unknown key. Workforce issuer/audience/JWKS are separate settings. Tokens only identify
a subject; permissions come from the database. Issuer binding prevents cross-authority subject reuse.
Workforce roles in staging require the configured workforce issuer.

Provision external identity bindings with `scripts/provision_identity.py`; supply the verified issuer,
subject, email, roles and operator identity explicitly. Customer/provider registrations in OIDC mode
are owned by Entra; the local registration endpoint rejects that mode. Do not enable demo header auth
outside isolated development. Marketplace users seeded with `larimia-local` cannot authenticate using
arbitrary demo headers.

No live Entra tenant login is claimed by local RSA token tests. Dedicated customer/provider/workforce
identities and their provisioning remain external staging setup.

Local sessions now carry sid and optional owned device binding. Refresh/logout/device revocation
invalidates the associated access tokens and WebSockets. See account-profiles-devices.md for client
rotation, identity-provider boundaries and migration/rollback requirements.
