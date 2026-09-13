# Realtime protocol

Connect to `ws://localhost:8000/api/v1/realtime` locally, or WSS on staging. Within ten seconds send:

```json
{"access_token":"<bearer token>","since":"2026-09-13T00:00:00+00:00","last_id":"00000000-0000-0000-0000-000000000000"}
```

Credentials go in the first protected frame, never a logged URL. The server checks signature/expiry,
issuer and persisted account binding, and rechecks expiry/account state while connected. Only that
user's durable notifications are streamed. Messages include type, event_type, id, created_at and data;
heartbeats contain type=heartbeat. Use the last event's created_at/id to resume and deduplicate IDs.
Refetch canonical booking/message APIs after reconnect; events are notifications, not authoritative state.

Domain events map to provider.assigned, dispatch.offer.created, provider.arrived, job.started,
job.completed, payment.completed and chat.message.created. The local polling gateway normally observes
worker deliveries within approximately two polling intervals. Azure Web PubSub is not required for the
current fallback; no claim of live Web PubSub verification is made.
