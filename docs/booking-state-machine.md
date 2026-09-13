# Booking state machine

Canonical path:

DRAFT → QUOTED → PAYMENT_AUTHORIZED → SEARCHING → OFFERED → ASSIGNED → PROVIDER_EN_ROUTE → ARRIVED →
IN_PROGRESS → COMPLETED → PAYMENT_CAPTURED → SETTLED.

Creation from an accepted quote starts at QUOTED. The complete transition table, including CANCELLED,
EXPIRED, NO_PROVIDER_FOUND, NO_SHOW, DISPUTED, REFUNDED and PARTIALLY_REFUNDED, is in
`marketplace/domain.py`. Presence in the domain state table does not imply every administrative
transition has a public endpoint; no generic arbitrary-state mutation is exposed.

Provider commands are `en-route`, `arrive`, `start`, `complete`. Completion and simulated capture/journal
creation commit atomically. Cancellation releases authorized mock payment holds and cancels offers.
Assigned provider workload is released on cancellation/completion. A captured booking can be disputed
or refunded through controlled workflows. Invalid jumps return BOOKING_INVALID_STATE / 409.

Each transition records actor, previous/new state, version, audit and outbox event in the command's
transaction. Duplicate command keys return the original completed response, even if canonical state
has subsequently advanced; clients should refetch the resource when they need current state.
