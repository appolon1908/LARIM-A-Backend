# Events and asynchronous delivery

Commands persist their business state, audit, outbox events and completed idempotency response in one
PostgreSQL transaction. Local notification consumption inserts unique event receipts and marks the
outbox processed in one transaction; replay cannot duplicate the in-app notification.

Azure transport adds a leased EventDelivery row. The publisher claims/commits a lease, sends outside
its DB transaction, and conditionally finalizes the same lease. Crash after a send can cause redelivery:
Service Bus message_id remains the stable outbox ID, and downstream consumers must retain durable inbox
uniqueness beyond the broker's deduplication window. Retry uses bounded exponential delay; after ten
attempts the delivery becomes DEAD_LETTER. Operations can inspect/replay it with integration.replay.

The in-app consumer is operational without Azure. Email/SMS protocols are retained in adapters/contracts.py;
external notification delivery/templates/preferences are not falsely reported as delivered.
No booking transaction waits for an SMS/email provider or Service Bus send.
