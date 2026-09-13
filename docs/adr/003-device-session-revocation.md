# ADR 003 — Server-side revocation for local device sessions

Status: accepted.

Device registration without token/session binding would imply a security control that it cannot
enforce. Local access tokens therefore reference their stored session using signed sid. Bind an
optional owned device at login and preserve it across refresh. Check session/device revocation in the
shared authorization function, including WebSocket reconnect and ongoing polling.

All owner/session/device mutations acquire the owner lock first; refresh and device revocation cannot
race to escape revocation. Session rotation invalidates old access tokens as well as refresh tokens.
This requires coordinated frontend replacement/reconnect, documented in the handoff.

Preserve compatibility with existing device-less clients and short-lived pre-migration tokens. Do not
interpret Entra sid claims as local session identifiers; external identity policies stay with Entra.
Rollback to older authentication requires invalidating local signing keys rather than silently losing
revocation enforcement. Store no raw push tokens in the generic device registry.
