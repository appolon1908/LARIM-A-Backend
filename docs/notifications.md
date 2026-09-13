# Durable notification delivery

In-app notifications remain a PostgreSQL projection of the transactional outbox. A separate
`larimia.marketplace.notification_delivery` process performs external fanout and delivery, independent
of booking, dispatch and the in-app worker. Compose and Azure runtime source include this process.

## Templates and preferences

Authenticated users GET/PUT `/api/v1/me/notification-preferences` with explicit email, sms and push
booleans. All external channels default to opt-out. In-app canonical state notifications remain
available regardless of these external preferences. A delivery rechecks account activation and
channel opt-in immediately before the vendor call; opt-out cannot recall a send already in flight.

Administrators with `notification.manage` PUT `/api/v1/admin/notifications/templates/{event_type}/{channel}`
and GET the templates collection. Templates are versioned, audited and support only literal text and
`$event_type`, `$user_id`, `$booking_id`, `$payout_id`, `$case_id`, `$message_id`. There is no executable
expression language. `$$` inserts a literal dollar sign. Seed creates default templates without
replacing operator changes. Templates cannot insert arbitrary event fields or credential data.

The worker atomically stores a rendered delivery snapshot and marks its in-app notification as
expanded. Unique notification/channel constraints and row locks prevent duplicate fanout. Later
template changes never alter an already queued message. A missing variable or oversized rendering
creates a `DEAD_LETTER` delivery while preserving the in-app notification.

## Adapters and state

`NotificationGateway.send(DeliveryRequest)` returns a `DeliveryReceipt`. The request contains a stable
delivery ID, recipient user ID, channel, subject and body. The integration must resolve that verified
platform user to its owned/verified destinations; clients cannot supply a callback URL or recipient
address to the delivery API.

- `LARIMIA_NOTIFICATION_MODE=disabled`: durable deliveries remain pending; no false success.
- `local`: explicit development-only mock; terminal state `SIMULATED`, no actual vendor send.
  Fresh `make setup` selects this local adapter. It is rejected in staging/production configuration.
- `relay`: fixed configured HTTPS endpoint and secret bearer, redirects disabled, 10-second timeout.
  Set `LARIMIA_NOTIFICATION_RELAY_URL` and `LARIMIA_NOTIFICATION_RELAY_TOKEN` externally. The relay
  receives JSON request fields and `Idempotency-Key: <delivery UUID>` and returns a 200/201/202 JSON
  receipt `{ "reference": "opaque-vendor-reference" }`. These responses record `ACCEPTED`, not proof
  of handset/email delivery. A future vendor-confirmation adapter can return `DELIVERED` explicitly.

Real relay/vendor provisioning and destination verification remain external integration work. The
repository does not advertise a built-in Twilio, FCM or email vendor connector. The relay contract is
vendor-neutral and the local adapter is a defined mock, not a placeholder in booking/payment code.

Workers commit two-minute leases before network I/O. Every attempt, including recovery after a crash,
counts toward the maximum of ten. Transient failures use capped exponential backoff; permanent
rejections dead-letter immediately. Stale lease completions cannot overwrite the current attempt.
The relay must deduplicate the stable delivery ID: network acknowledgement loss can cause retries.
Only sanitized exception class names are stored, never vendor response bodies or authorization values.

Users GET `/me/notification-deliveries` for owned, bounded delivery history. Administrators GET
`/admin/notifications/dlq` and POST `/admin/notifications/deliveries/{id}/replay`. Mutations require
Idempotency-Key; replay is audited and preserves the vendor idempotency identity. Invalid template
snapshots cannot be replayed as empty messages; correct the template for future events.

## Azure and verification

Optional runtime Bicep parameters `notificationRelayUrl` and `notificationTokenSecretUri` activate the
relay only for the notification container. Grant its managed identity read access to that Key Vault
secret. The API container receives no notification bearer environment variable. With no parameters,
external delivery stays disabled while in-app delivery continues.

Tests cover template validation/render failure, snapshot stability, opt-out, ownership/permissions,
deduplication, bounded retries, audited replay, expired leases, relay status classification and standalone
worker imports. `scripts/certify.py --require-notifications` enables email for dedicated demo identities
and verifies a related asynchronous receipt. CI starts a separate local notification worker and requires
this check; it does not contact external vendors.
