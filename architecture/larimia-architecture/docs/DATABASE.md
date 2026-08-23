# Database Design

## Core Rules

- UUID primary keys
- UTC timestamps (`timestamptz`)
- money in integer minor units
- ISO currency codes
- optimistic `version` on concurrent aggregates
- `jsonb` only for snapshots/policies/events, not as a substitute for modeled relational data
- PostGIS `geography` for zones and coordinates
- append-only ledger/audit/event data
- PII separated where practical

## Core Tables

```text
accounts
persons
roles
account_roles

customers
customer_addresses
customer_preferences
consents

providers
provider_services
provider_credentials
provider_documents
provider_kits
provider_service_zones

markets
market_policies
feature_flags

service_categories
services
service_addons
catalog_versions

availability_rules
availability_exceptions
capacity_holds

price_policies
quotes
quote_lines

bookings
booking_services
booking_status_history

dispatch_runs
dispatch_offers
assignments
travel_estimates

visits
visit_events
visit_checkins

conversations
conversation_participants
messages

payment_intents
charges
refunds
payment_disputes

ledger_accounts
ledger_transactions
ledger_entries

provider_earnings
payout_batches
payout_items
reconciliation_breaks

memberships
subscriptions
credits

partners
partner_users
partner_contracts
partner_invoices

reviews
quality_cases
safety_incidents
support_cases

audit_events
outbox_events
inbox_receipts
```

## Double-Booking Protection

Provider assignments require a PostgreSQL exclusion constraint over a time range.

Conceptually:

```sql
EXCLUDE USING gist (
    provider_id WITH =,
    service_period WITH &&
)
WHERE (status IN ('HELD', 'ASSIGNED', 'ACTIVE'));
```

Application code may pre-check availability for user experience, but the database is the final concurrency guard.

## Quote Snapshot

A confirmed quote stores:

```text
market
currency
policy version
service lines
duration
travel/zone charges
discounts
membership use
tax
provider compensation basis
cancellation version
expiry
integrity hash
```

The confirmed booking never recalculates historical commercial terms from the live catalog.
