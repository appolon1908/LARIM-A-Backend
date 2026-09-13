# Authorization

`marketplace/security.py` defines reusable permission checks. Roles include customer, provider,
support, dispatcher, finance, safety, catalog manager, operations manager, administrator and super admin;
uppercase mission/Entra app-role aliases resolve to the same grants. Roles are persisted, never accepted
from a login request or trusted from demo headers for marketplace authorization.

Ownership is checked for addresses, quotes, bookings, offers, documents and conversations. Unknown or
foreign resources return 404 where appropriate. Only an assigned approved provider can progress a job.
Suspension is rechecked during offer acceptance and every job mutation. Finance permissions control
refunds/payouts; support cannot browse safety cases or mutate finance. Role changes reject self-editing
and create an append-only audit event. Workforce enforcement requires the separate verified issuer.

The default administrator role intentionally has all permissions. Apply narrower operational roles
for ordinary users. The Azure runtime database role has no schema/role creation rights and no UPDATE
rights on immutable journal/audit tables; migration uses a separate identity and Key Vault scope.
