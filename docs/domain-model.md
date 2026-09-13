# Domain model

| Boundary | Persisted aggregates / value objects |
|---|---|
| Identity | User, issuer binding, persisted roles, RefreshSession, append-only LoginSucceeded audit |
| Customer | Owned Address, Block, User profile |
| Provider | Provider profile; approval state, verified-by-review skills, services, UTC availability windows, service area and performance values |
| Catalog/pricing | Service, Promotion, versioned rules, expiring Quote and immutable accepted snapshot |
| Booking/jobs | MarketplaceBooking, StatusHistory, assignment, provider progression, snapshotted ServiceJobPolicy, JobChecklistItem, JobTimeEntry and private booking evidence |
| Dispatch | DispatchSession and Offer with score, attempt, expiry and winner serialization |
| Money | Payment, Refund, LedgerAccount, LedgerTransaction, LedgerEntry, Earning, Payout |
| Communication | Versioned NotificationTemplate, NotificationPreference, leased NotificationDelivery; Conversation, Message, Notification; conversation participants derive from booking ownership |
| Support/safety | Case with kind, owner, optional booking, lifecycle and resolution; booking dispute transition |
| Storage | Document, owner, digest, size, MIME and quarantine state |
| Integration | OutboxEvent, InboxReceipt, leased EventDelivery and audit records |

Availability, service requirements, pricing components, address snapshots and payout item references
are embedded aggregate values rather than independent microservices. This implementation does not
claim every named future entity in the mission as a separate completed domain: devices, banking
onboarding, customer preference management, paid job extras and read receipts,
review reporting, risk scoring remain extensions.
Core lifecycle routes do not silently simulate those features.

Foreign keys and unique constraints protect financial/event references and accepted quotes. Monetary
values are integer minor units; decimals are used for percentage rounding. GPS/scoring use floating
point only for non-financial quantities. PostGIS expression indexes cover address and provider locations.
