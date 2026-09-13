# Mission 2 — Exact frontend handoff

Backend canonical base: `/api/v1`; `/v1` aliases are retained where implemented. Local default:
`http://localhost:8000/api/v1`. Cloud base URL remains unset until deployment. Contract:
`openapi.generated.json`; realtime protocol: `docs/realtime.md`.

1. Pass a token callback to both Nuxt `useLarimiaApi` composables. Local POST auth/login returns
   access_token/refresh_token. Staging obtains customer/provider and workforce tokens from the
   configured Entra authorities; backend roles must be provisioned. Never send X-Demo-Roles.
2. Replace `demo-address` with an owned UUID from POST/GET `/me/addresses`. Quote request retains
   service_code, market_code, currency, scheduled_start and empty add_ons. Unsupported add-ons fail 422.
3. Persist quote.id across book → checkout. POST `/bookings` with `{quote_id}`. Do not send customer_id,
   client totals or arbitrary booking status. POST `/payments/authorize` with booking_id and vendor
   payment_method_token; local tokens are explicitly `mock_success` / `mock_declined`.
4. `/bookings/{id}/confirm` is a compatibility alias for dispatch **after** payment authorization.
   It no longer blindly marks a booking confirmed. GET `/bookings` supplies the customer list;
   GET detail and `/receipt` supply canonical state and financial receipt.
5. Booking responses include camelCase bookingNumber/scheduledStart/total for the shared summary;
   update the status union: CONFIRMED→PAYMENT_AUTHORIZED, MATCHING→SEARCHING/OFFERED,
   EN_ROUTE→PROVIDER_EN_ROUTE, IN_SERVICE→IN_PROGRESS, SETTLING→PAYMENT_CAPTURED. Add terminal side states.
6. Persist provider online changes with PUT `/provider/status`; availability uses explicit UTC start/end
   windows at PUT `/provider/availability`. GET `/providers/me` is retained. Read offers via
   `/dispatch/offers` or `/provider/offers`; send current booking_version when accepting.
7. Provider job actions are POST `/provider/jobs/{booking_id}/en-route|arrive|start|complete`.
   Send PUT `/provider/location` periodically while active. Completion triggers simulated capture and
   earning creation. Show errors for suspended providers, expired offers or illegal transitions.
8. Operations aliases dispatch/ops/board, safety/ops/incidents, support/ops/cases and
   finance/reconciliation-breaks remain. Use the protected `/admin/*` APIs for real rows and actions.
   Replace all static counters, provider tables and empty financial displays.
9. Reuse the **same Idempotency-Key for retries of the same logical command**. The current client
   generates a new key per method invocation, which is unsafe for retry orchestration.
10. Read errors at body.error.code/message/details/trace_id. The current ApiError reads top-level fields;
    update that parser. A replayed response is historical; fetch current state when needed.
11. Replace unauthenticated topic-specific sockets with `/api/v1/realtime` and first-frame access_token.
    Resume using created_at/id, deduplicate event IDs and refetch canonical APIs on reconnect.
12. File uploads use bounded base64 payloads and return private document IDs/quarantine state; never
    treat a received file as verified. Download requires an authorized bearer and ownership.

Demo accounts are listed in README; passwords are generated in the ignored `.env`, not in this handoff.
Membership purchase, partner commercial booking, dynamic add-ons, rich job checklists and external
notification preference screens must not advertise supported behavior before their backend extensions
are implemented. Legacy booking rows remain operations-only until reviewed migration mapping exists.
