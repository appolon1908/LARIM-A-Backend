# Owned profiles, preferences and local device sessions

GET/PUT `/api/v1/me/profile` stores display_name, locale and an IANA timezone. GET/PUT
`/api/v1/me/preferences` stores bounded preferred_service_codes, accessibility_notes and a contact
preference. These are private owner-scoped projections, not inputs to identity/role assignment or
pricing. Contact preference does not opt a user into external notifications; those settings remain
under `/me/notification-preferences`. Mutations require Idempotency-Key and produce audit entries
without copying private notes into audit metadata.

POST `/me/devices` registers a server-generated device ID from a label and platform (web/ios/android).
GET the bounded collection and DELETE an owned device ID to revoke it. Up to 50 active devices are
allowed per user. Registration is idempotent. Another user's device cannot be bound, read or revoked.
The registry does not store raw push tokens or claim to complete external push-vendor registration.

## Local authentication sequence

1. Log in normally to obtain the bootstrap local credentials.
2. Register the installation with POST `/me/devices`.
3. Log in with the same credentials plus the returned `device_id` to obtain device-bound credentials.
4. Use returned access/refresh tokens. Refresh preserves the device binding and rotates the session.

Every newly issued local access token contains a signed `sid` referencing its stored refresh session.
API and WebSocket authentication check that the session belongs to the user, is active/unexpired and
its device remains active. Device revocation atomically revokes all associated refresh sessions.
Logout and refresh rotation also invalidate the corresponding old access token. The frontend must
atomically replace both tokens and reconnect realtime after refresh; it must not keep using the old
access token until its original expiry.

Session/device mutations lock the owner first. A concurrent refresh cannot create an active replacement
session after device revocation. Long-lived WebSockets revalidate on each polling cycle and close with
1008 when revoked. Integration tests cover ownership, idempotent registration, refresh/logout revocation,
concurrent refresh-versus-revocation and an already-open WebSocket closing after revocation.

Unbound sessions still work for backward-compatible local clients. Pre-migration local tokens without
sid remain valid until their original short expiry; they were never bound to a device. Newly issued
tokens always have sid. OIDC/Entra sessions and device policies remain owned by the configured identity
provider; this feature does not claim to revoke external identity-provider tokens. Local login, refresh
and logout endpoints explicitly reject OIDC mode.

## Migration and rollback

0010 adds account_profiles, account_devices and nullable refresh_sessions.device_id with foreign keys
and indexes. Existing sessions retain their existing device-less association. Migrate before deploying
this code. A rollback must retain session-aware validation. Rolling back to pre-0010 authentication
could accept access tokens whose sessions have been revoked; if such a rollback is unavoidable, rotate
the local signing key and redeploy all replicas to invalidate outstanding local tokens. No automatic
schema downgrade deletes revocation history.

Provider banking onboarding and saved external payment-method management remain separate work; this
feature does not collect bank account numbers or card data through generic profile fields.
