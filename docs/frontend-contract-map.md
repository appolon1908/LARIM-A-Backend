# Frontend contract discovery

Read-only source: appolon1908-hue/LARIM-A-Fornt-end, main, inspected all application Vue/TypeScript sources and shared packages. No frontend edits are part of this mission. Inspected commit: `fc594e38a78e74b6f566ec88ba3e5f4d3dcc3609`.

| Source | Existing behavior | Backend contract |
|---|---|---|
| packages/api-client/src/index.ts | Bearer callback, request IDs, mutation idempotency keys; defaults /v1 | Retain /v1 compatibility; canonical /api/v1 |
| packages/domain/src/index.ts | camelCase BookingSummary; minor-unit money, legacy statuses | Include compatibility summary fields; document canonical status mapping |
| customer-web/pages/index.vue | Localized catalog, market DO-SDQ | GET /catalog, persistent services |
| customer-web/pages/book.vue | Quote service_code/address_id/scheduled_start/add_ons | Owned persisted address, server price and expiring quote |
| customer-web/pages/checkout.vue | Static payment button, no payment integration | Accept quote, authorize payment via tokenized adapter |
| customer-web/pages/bookings.vue | Static empty list | GET /bookings and detail |
| customer-web/pages/membership.vue | Static commercial claims | Membership implementation not established by the UI |
| customer-web/pages/safety.vue | Static SOS | Authenticated safety incident submission |
| customer-mobile/src/App.vue | Static four-service list | Catalog/booking APIs; no HTTP wiring exists |
| pro-mobile/src/App.vue | Local-only online toggle, static offers/earnings | Persist approval, availability, presence, offers/jobs/earnings |
| ops-web/pages/index.vue | dispatchBoard() | GET /dispatch/ops/board with role checks |
| ops-web/pages/dispatch,providers,finance,catalog,safety,partners.vue | Mostly static display | Persistent operations APIs; partner commercial scope remains separate |
| packages/api-client/src/realtime.ts | Reconnect backoff, no credential transport or resume cursor | Bearer-authenticated first frame; refetch canonical state |
| apps/*-web/app/composables/useLarimiaApi.ts | Does not supply token callback | Mission 2 must wire identity before private requests can succeed |

The only active customer HTTP features are catalog and quote. Shared client also specifies markets, availability, booking create/get/confirm/cancel, providers/me, dispatch offer accept/decline, operations board, safety incidents, support cases and finance reconciliation. The full marketplace flow is a backend mission requirement, not an already implemented frontend flow.
