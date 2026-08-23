# ODOO_CAMPAIGN_CRM_IMPLEMENTATION.md

## Purpose

This document is the implementation authority for building the LARIMÍA Odoo CRM, campaign, sales, provider-recruitment, partner-sales, and CRM projection layer.

The LARIMÍA core application remains the source of truth for:

- bookings
- provider eligibility
- provider availability
- matching
- dispatch
- visit state
- safety state
- payments
- payouts
- ledger/accounting truth
- membership entitlements
- service availability
- credentials
- provider activation

Odoo is a controlled CRM and operating projection layer. It must never write directly to LARIMÍA PostgreSQL tables.

## Repository Placement

Place this document in the repository that owns Odoo custom addons and Odoo deployment files:

```text
docs/codex/ODOO_CAMPAIGN_CRM_IMPLEMENTATION.md
```

Recommended repository layout:

```text
odoo/
├── addons/
│   ├── larimia_crm_core/
│   ├── larimia_crm_campaigns/
│   ├── larimia_crm_provider/
│   ├── larimia_crm_partner/
│   ├── larimia_crm_support/
│   └── larimia_crm_integration/
├── config/
├── deploy/
├── tests/
└── docs/
    └── codex/
        └── ODOO_CAMPAIGN_CRM_IMPLEMENTATION.md
```

---

# CODEX IMPLEMENTATION ORDER

Implement in this order.

## 1. `crm/odoo-campaign-core`

This is the mandatory first implementation target.

Do not start campaign automation, provider recruiting, partner sales, or support workflow until this foundation is complete and green.

The first target must deliver:

- LARIMÍA CRM security groups
- market/team ownership model
- CRM-safe customer projection
- CRM-safe provider projection
- booking summary projection
- partner account projection
- integration-event tracking
- campaign attribution fields
- record rules
- field-level groups
- menus
- base views
- integration API/client boundary
- tests
- migration-safe data definitions

After `crm/odoo-campaign-core` passes its definition of done, implement:

```text
crm/odoo-campaign-customer
crm/odoo-campaign-provider
crm/odoo-campaign-partner
crm/odoo-campaign-support
crm/odoo-campaign-automation
crm/odoo-campaign-reporting
```

---

# MASTER RULE

Odoo is not marketplace authority.

Correct direction:

```text
LARIMÍA Core
    ↓
Domain Event
    ↓
Transactional Outbox
    ↓
Integration Worker
    ↓
Odoo Adapter / Control Plane
    ↓
Odoo CRM Projection
```

Approved inbound Odoo actions:

```text
Odoo
  ↓
Approved Action
  ↓
LARIMÍA API
  ↓
Authorized Domain Command
```

Never allow:

```text
Odoo → direct PostgreSQL write
Odoo → direct booking status mutation
Odoo → direct provider activation
Odoo → direct payment capture
Odoo → direct refund
Odoo → direct payout
Odoo → direct credential approval
Odoo → direct safety state mutation
```

---

# 1. ODOO APPLICATIONS / MODULE DEPENDENCIES

Use standard Odoo modules where available.

Required dependencies:

```text
base
contacts
crm
sale_management
mail
calendar
marketing_automation
mass_mailing
sms
helpdesk
documents
sign
spreadsheet_dashboard
```

Do not duplicate features already available in Odoo core unless LARIMÍA-specific authorization or projection behavior requires a custom layer.

---

# 2. CUSTOM ADDON STRUCTURE

Create:

```text
addons/larimia_crm_core/
├── __init__.py
├── __manifest__.py
│
├── models/
│   ├── __init__.py
│   ├── res_users.py
│   ├── crm_lead.py
│   ├── res_partner.py
│   ├── larimia_customer_profile.py
│   ├── larimia_provider_profile.py
│   ├── larimia_booking_projection.py
│   ├── larimia_partner_account.py
│   ├── larimia_campaign_attribution.py
│   ├── larimia_integration_event.py
│   └── larimia_market.py
│
├── security/
│   ├── groups.xml
│   ├── record_rules.xml
│   └── ir.model.access.csv
│
├── views/
│   ├── menu.xml
│   ├── crm_lead_views.xml
│   ├── customer_views.xml
│   ├── provider_views.xml
│   ├── booking_projection_views.xml
│   ├── partner_views.xml
│   ├── integration_views.xml
│   └── user_views.xml
│
├── data/
│   ├── crm_stages.xml
│   ├── activity_types.xml
│   └── sequences.xml
│
├── services/
│   ├── __init__.py
│   └── larimia_api_client.py
│
├── controllers/
│   ├── __init__.py
│   └── webhook.py
│
└── tests/
    ├── __init__.py
    ├── test_access_rights.py
    ├── test_record_rules.py
    ├── test_market_isolation.py
    ├── test_team_visibility.py
    ├── test_field_security.py
    └── test_projection_upsert.py
```

---

# 3. SECURITY GROUPS

Create the following groups.

```text
larimia.group_customer_agent
larimia.group_provider_recruiter
larimia.group_partner_sales_agent
larimia.group_support_agent
larimia.group_supervisor
larimia.group_crm_manager
larimia.group_marketing_manager
larimia.group_integration_admin
larimia.group_safety_restricted
larimia.group_finance_restricted
```

Do not use `base.group_system` as a substitute for business permissions.

Business users must receive the minimum required group combination.

---

# 4. USER SECURITY MODEL

Extend `res.users` with:

```python
larimia_market_ids
larimia_supervised_user_ids
larimia_team_code
larimia_can_take_unassigned_leads
larimia_max_credit_approval_minor
larimia_partner_account_ids
```

Security decisions combine:

```text
model access
+
group
+
market
+
team
+
record owner
+
partner organization
+
restricted-data group
```

Hidden menus are not security.

Every sensitive model must have explicit access and record rules.

---

# 5. MARKETS

Create:

```text
larimia.market
```

Fields:

```text
name
code
country_code
currency_code
timezone
active
```

Seed:

```text
DO-SDQ
DO-PUJ
DO-STI
```

Allow future:

```text
US-MIA
US-NYC
```

Users receive one or more permitted markets.

All LARIMÍA CRM projection records require `market_id`.

---

# 6. CUSTOMER CRM PROJECTION

Create:

```text
larimia.customer.profile
```

Fields:

```text
larimia_customer_id         Char, indexed, unique
partner_id                  Many2one(res.partner)
market_id                   Many2one(larimia.market)
crm_owner_id                Many2one(res.users)

preferred_language          Selection(es_DO, en_US)
customer_status             Selection
membership_status           Selection
membership_plan_code        Char

customer_since              Datetime
last_completed_booking_at   Datetime
next_booking_at             Datetime
last_service_code           Char
completed_booking_count     Integer
lifetime_value_minor        Integer
currency_code               Char

first_touch_source          Char
last_touch_source           Char
utm_source                  Char
utm_medium                  Char
utm_campaign                Char

service_interest_codes      Text/JSON-safe field
crm_segment                 Selection
retention_status            Selection

marketing_email_allowed     Boolean
marketing_sms_allowed       Boolean
transactional_sms_allowed   Boolean

projection_version          Integer
last_projected_at           Datetime
```

Do not store:

```text
card tokens
raw card data
customer password data
authentication tokens
live GPS
private safety notes
medical/health information
raw incident evidence
```

---

# 7. PROVIDER CRM PROJECTION

Create:

```text
larimia.provider.profile
```

Fields:

```text
larimia_provider_id
partner_id
market_id
recruiter_id

provider_status
onboarding_status
requested_service_codes
approved_service_codes

credential_summary
training_status
kit_status
activation_readiness

quality_band
completed_service_count
last_active_at
activated_at

projection_version
last_projected_at
```

Do not store in this general CRM projection:

```text
raw government ID
raw background check
bank account
payout token
full safety investigations
credential document bodies
```

If restricted documents are ever projected, use a separate restricted model and group.

---

# 8. BOOKING CRM PROJECTION

Create:

```text
larimia.booking.projection
```

This is read-only for ordinary CRM users.

Fields:

```text
larimia_booking_id
booking_number
customer_profile_id
provider_profile_id
partner_account_id

market_id
service_code
service_name

booking_status
scheduled_start
scheduled_end
completed_at

currency_code
customer_total_minor

venue_type
hotel_or_property_name

campaign_attribution_id

projection_version
last_projected_at
```

Do not expose:

```text
payment method
payment processor secrets
provider payout
ledger entries
live location
arrival PIN
safety evidence
```

---

# 9. PARTNER / HOTEL ACCOUNT MODEL

Create:

```text
larimia.partner.account
```

Fields:

```text
partner_id
market_id
account_owner_id

account_type
hotel
villa_manager
property_manager
corporate
event_planner

property_count
room_count
estimated_monthly_guest_volume

pipeline_status
contract_status
pilot_status

commercial_value_minor
currency_code

contract_start
contract_end
renewal_date

larimia_partner_id
projection_version
```

---

# 10. CRM LEAD EXTENSION

Extend `crm.lead`.

Add:

```text
larimia_lead_type
larimia_market_id
larimia_customer_profile_id
larimia_provider_profile_id
larimia_partner_account_id

larimia_source_event
larimia_campaign_code
larimia_external_reference

larimia_retention_reason
larimia_loss_reason_code

larimia_sensitive
larimia_projection_only
```

Allowed lead types:

```text
CUSTOMER_ACQUISITION
CUSTOMER_RETENTION
PROVIDER_RECRUITMENT
PARTNER_SALES
CORPORATE_SALES
SUPPORT_RECOVERY
```

---

# 11. CRM PIPELINES

Create separate sales teams and stages.

## Customer Acquisition

Stages:

```text
NEW
CONTACT_ATTEMPTED
QUALIFIED
BOOKING_INTENT
FIRST_BOOKING
ACTIVATED
```

Loss reasons:

```text
NO_RESPONSE
PRICE
UNAVAILABLE_SERVICE
OUTSIDE_ZONE
NOT_READY
DUPLICATE
INVALID_CONTACT
OTHER
```

## Customer Retention

```text
ACTIVE
REBOOK_OPPORTUNITY
CONTACTED
OFFER_PRESENTED
REBOOKED
AT_RISK
RECOVERY
RETAINED
CHURNED
```

## Provider Recruitment

```text
NEW_CANDIDATE
CONTACTED
INTERESTED
APPLICATION_STARTED
APPLICATION_SUBMITTED
VERIFICATION
TRAINING_ASSESSMENT
READY_FOR_ACTIVATION
ACTIVATED
REJECTED
WITHDRAWN
```

## Hotel / Corporate

```text
TARGET_ACCOUNT
CONTACT_IDENTIFIED
DISCOVERY
QUALIFIED
DEMO_PROPOSAL
COMMERCIAL_NEGOTIATION
LEGAL_PROCUREMENT
CONTRACTED
ONBOARDING
LIVE
AT_RISK
RENEWAL
```

---

# 12. ACCESS CONTROL — CUSTOMER AGENT

Customer agents may read:

```text
their assigned leads
their assigned customers
permitted unassigned queue
customer contact details
market
language
service interest
booking summaries
membership summary
campaign participation
CRM communication history
activities
approved offer metadata
```

Customer agents may write:

```text
lead stage
CRM notes
follow-up
activity
loss reason
campaign disposition
approved communication preferences
```

Customer agents may not access:

```text
other agents' private leads
provider financial data
payout data
platform finance
safety incidents
identity documents
background checks
payment instruments
ledger
integration credentials
security audit
```

---

# 13. ACCESS CONTROL — PROVIDER RECRUITER

May read:

```text
assigned candidates
candidate contact details
requested services
market
application progress
high-level verification status
training progress
activation readiness
CRM activity
```

May write:

```text
recruitment pipeline stage
recruitment notes
activities
candidate disposition
```

May not read:

```text
raw background check
raw ID
bank account
payout account
restricted safety complaints
ledger
provider earnings
```

---

# 14. ACCESS CONTROL — PARTNER SALES AGENT

May read:

```text
assigned partner accounts
contacts
sales pipeline
meeting notes
proposal summary
contract status
booking volume summary
invoice summary
```

May write:

```text
partner opportunity stage
activities
CRM notes
proposal status
renewal tracking
```

May not read:

```text
general consumer customer database
provider payout
safety incidents
payment instruments
other sales territories without access
```

---

# 15. ACCESS CONTROL — SUPPORT AGENT

May read:

```text
assigned CRM support cases
customer identity required for support
booking summaries
approved service recovery information
```

May not read:

```text
restricted safety evidence
full financial ledger
provider bank/payout records
raw identity docs
integration credentials
```

Refund authority must not be granted simply because a user is a support agent.

If refund requests are initiated in Odoo, they must call an approved LARIMÍA command and require backend authorization.

---

# 16. ACCESS CONTROL — SUPERVISOR

Supervisor visibility:

```text
own records
team member records
team unassigned queue
team campaigns
team activities
team SLA breaches
team pipeline
team performance
```

Supervisor may:

```text
assign
reassign
approve limited CRM offers
review agent activities
close stale leads
escalate support
approve campaign exceptions
```

Supervisor may not automatically access:

```text
other supervisors' teams
restricted safety
executive finance
payment credentials
raw verification docs
integration secrets
security configuration
```

---

# 17. ACCESS CONTROL — CRM MANAGER

CRM Manager may access:

```text
all customer CRM
all provider recruitment CRM
all partner CRM
all ordinary campaign results
sales teams
CRM configuration
CRM reporting
```

CRM Manager does not automatically receive:

```text
Safety Restricted
Finance Restricted
Integration Admin
Odoo System Administrator
```

---

# 18. ACCESS CONTROL — MARKETING MANAGER

Marketing Manager may:

```text
create campaigns
create audiences
create templates
schedule campaigns
view aggregate performance
manage UTM taxonomy
manage segments
run A/B tests
```

Marketing Manager must not automatically access:

```text
private safety records
raw identity docs
provider bank/payout records
booking mutation actions
dispatch controls
integration secrets
```

Customer PII available to marketing must be minimized to campaign need.

---

# 19. RECORD RULES

Implement record rules programmatically/XML.

## Customer Agent

Pseudo-domain:

```python
[
    '&',
        ('market_id', 'in', user.larimia_market_ids.ids),
        '|',
            ('crm_owner_id', '=', user.id),
            '&',
                ('crm_owner_id', '=', False),
                ('user.larimia_can_take_unassigned_leads', '=', True)
]
```

Use actual valid Odoo domain syntax and/or computed allowed ownership fields as needed.

Do not attempt to reference arbitrary Python expressions that Odoo record rules cannot evaluate.

## Supervisor

Allowed records:

```text
record market ∈ supervisor markets
AND
owner ∈ {supervisor + supervised users}
```

## Partner Sales

Allowed records:

```text
record market ∈ user markets
AND
(
  owner == user
  OR partner_account ∈ user permitted partner accounts
)
```

## Manager

Functional managers receive global rules only for their functional area.

Do not use a single rule that accidentally opens unrelated models.

---

# 20. FIELD-LEVEL SECURITY

Use field groups where sensitive business fields exist.

Examples:

```text
provider verification detail
restricted account flags
commercial value
invoice summary
campaign suppression reason
integration status/error
```

Restricted field groups:

```text
larimia.group_finance_restricted
larimia.group_safety_restricted
larimia.group_integration_admin
```

Prefer separate models for highly sensitive data rather than putting all sensitive fields on `res.partner`.

---

# 21. CUSTOMER CRM FORM LAYOUT

Create notebook tabs:

```text
Overview
Activity
Bookings
Campaigns
Support
Attribution
```

Header:

```text
Customer Name
Status
Market
CRM Owner
Membership
```

Overview cards:

```text
Customer Since
Completed Bookings
Last Service
Next Booking
Membership
Retention Status
```

Do not show restricted information.

---

# 22. PROVIDER CRM FORM LAYOUT

Tabs:

```text
Recruitment
Activity
Eligibility Summary
Training
Campaigns
CRM Timeline
```

Header:

```text
Provider Name
Market
Recruiter
Provider Status
Onboarding Status
```

Show high-level readiness only.

---

# 23. PARTNER FORM LAYOUT

Tabs:

```text
Overview
Contacts
Pipeline
Commercial
Bookings
Invoices
Activities
Campaign Attribution
```

Header:

```text
Partner
Account Type
Market
Account Owner
Contract Status
Pilot Status
```

---

# 24. AGENT DASHBOARD

Build dashboard metrics:

```text
New Leads
Due Today
Follow-ups
Converted / Booked
Overdue Activities
```

Show:

```text
My Pipeline
Today's Activities
My Campaign Participants
My Recent Conversions
```

Only records permitted by record rules may contribute.

---

# 25. SUPERVISOR DASHBOARD

Show:

```text
Team Conversion
Lead Response SLA
Leads per Agent
Bookings Generated
Pipeline Aging
Unassigned Queue
Overdue Activities
Campaign Conversion
Loss Reasons
Agent Workload
```

Do not rank agents solely on revenue.

Include quality-related KPIs.

---

# 26. EXECUTIVE CRM DASHBOARD

Show aggregate:

```text
Acquisition
Retention
Provider Recruitment
B2B Pipeline
Campaign Performance
```

No raw safety or payment data on executive CRM dashboard.

---

# 27. CAMPAIGN FAMILY — NEW CUSTOMER ACTIVATION

Target:

```text
customer created
AND
no booking
```

Automation sequence:

```text
+2h   welcome
+24h  service discovery
+72h  convenience / trust
+7d   booking reminder
```

Exit conditions:

```text
booking confirmed
unsubscribe
suppressed
account inactive
```

Never continue promotional automation after suppression.

---

# 28. CAMPAIGN FAMILY — ABANDONED QUOTE

Target:

```text
quote created
AND
not confirmed
AND
quote still actionable
```

Sequence:

```text
+30m reminder
+24h service reminder
+48h final follow-up
```

CRM-safe fields:

```text
customer
service
market
quote amount
quote expiry
```

Do not show internal payment failure details to normal agents.

---

# 29. CAMPAIGN FAMILY — REBOOK

Target:

```text
completed booking
AND
service-specific rebook window reached
```

Example strategy:

```text
haircut          21–42 days
massage          policy-configured
makeup           event-driven
training         recurring-plan driven
hair styling     event/recurring
```

Do not hard-code these values permanently.

Store campaign policy/configuration so the business can change them.

Campaign CTA must deep-link to LARIMÍA booking.

Odoo must not create a marketplace booking directly unless using the approved LARIMÍA partner/customer booking command.

---

# 30. CAMPAIGN FAMILY — MEMBERSHIP

Target segments:

```text
repeat customer
frequent customer
multi-category customer
high-value customer
hotel/villa customer
```

Lifecycle:

```text
ELIGIBLE
BENEFITS_EDUCATION
OFFER
SIGNUP
```

Membership activation is authoritative in LARIMÍA.

Odoo receives resulting membership status.

---

# 31. CAMPAIGN FAMILY — WIN BACK

Segments:

```text
30_DAY_INACTIVE
60_DAY_INACTIVE
90_DAY_INACTIVE
HIGH_VALUE_AT_RISK
```

Use:

```text
personal reminder
previous category
favorite professional where permitted
membership value
service discovery
```

Do not automatically issue uncontrolled discounts.

Discount entitlements must come from LARIMÍA pricing/promotion authority.

---

# 32. CAMPAIGN FAMILY — PROVIDER RECRUITMENT

Segments:

```text
MASSAGE
BARBER
HAIR_STYLIST
MAKEUP
PERSONAL_TRAINER
DO_SDQ
DO_PUJ
DO_STI
```

Automation:

```text
recruitment introduction
benefits
application link
application reminder
training reminder
```

Exit:

```text
ACTIVATED
REJECTED
WITHDRAWN
DO_NOT_CONTACT
```

---

# 33. CAMPAIGN FAMILY — HOTEL / CORPORATE

Segments:

```text
luxury hotel
boutique hotel
villa manager
property manager
event planner
corporate wellness
```

Stages:

```text
INTRODUCTION
USE_CASE
MEETING
PILOT
PARTNERSHIP
```

Track:

```text
rooms
property count
market
guest volume
decision maker
concierge contact
contract value
pilot status
```

---

# 34. CAMPAIGN ATTRIBUTION MODEL

Create:

```text
larimia.campaign.attribution
```

Fields:

```text
campaign_code
campaign_name
utm_source
utm_medium
utm_campaign
utm_content
utm_term

first_touch
last_touch

customer_profile_id
lead_id
booking_projection_id

attributed_booking_count
attributed_value_minor
currency_code

first_seen_at
last_seen_at
```

Do not claim perfect causal attribution.

Keep explicit:

```text
first-touch
last-touch
campaign-associated
```

as distinct concepts.

---

# 35. LARIMÍA → ODOO EVENT MAPPING

Support idempotent upsert for:

```text
customer.created.v1
customer.updated.v1
customer.first_booking_completed.v1

booking.confirmed.v1
booking.completed.v1
booking.cancelled.v1

membership.started.v1
membership.cancelled.v1

provider.application_started.v1
provider.application_submitted.v1
provider.activated.v1
provider.suspended.v1

partner.created.v1
partner.updated.v1
partner.booking_completed.v1

customer.support_escalated.v1
```

Each projection update must store:

```text
event_id
event_type
aggregate_id
aggregate_version
received_at
processed_at
status
error
```

Reject stale projection versions.

Duplicate event ID must produce one effect.

---

# 36. INTEGRATION EVENT MODEL

Create:

```text
larimia.integration.event
```

Fields:

```text
event_id
event_type
aggregate_type
aggregate_id
aggregate_version
correlation_id
causation_id

payload_hash
status

received_at
processed_at
attempt_count
last_error
```

Unique:

```text
event_id
```

Projection application must be idempotent.

---

# 37. ODOO → LARIMÍA ALLOWLISTED ACTIONS

Allowed initial actions:

```text
request customer callback
request approved customer notification
create support case
request provider recruitment invitation
create partner booking request
request approved promotion assignment
```

Implement through:

```text
larimia_api_client.py
```

Every outbound command requires:

```text
service authentication
request ID
correlation ID
idempotency key
actor identity
operation code
```

No direct DB write.

---

# 38. LARIMÍA API CLIENT

Create a service:

```python
class LarimiaApiClient:
    def request_customer_callback(...)
    def create_support_case(...)
    def request_provider_invitation(...)
    def create_partner_booking(...)
    def assign_approved_promotion(...)
```

Requirements:

```text
timeout
bounded retries for safe operations
idempotency
correlation ID
structured error handling
no secret logging
```

Do not retry non-idempotent calls unless protected by idempotency key.

---

# 39. CAMPAIGN CONSENT RULES

Every campaign must honor LARIMÍA-projected consent/preferences.

Before email:

```text
marketing_email_allowed == True
```

Before marketing SMS:

```text
marketing_sms_allowed == True
```

Transactional messages must be clearly separated from marketing.

Do not let agents override suppression casually.

Suppression changes require authorized workflow and audit.

---

# 40. AUDIT REQUIREMENTS

Audit:

```text
lead ownership change
lead stage change
manual campaign enrollment
manual campaign removal
suppression change
partner commercial status change
provider recruitment disposition
manual outbound command to LARIMÍA
restricted field access where feasible
```

Use Odoo chatter for ordinary CRM history, but do not rely on chatter as the only security audit mechanism for privileged actions.

---

# 41. AUTOMATION SAFETY

Campaign automation must include:

```text
maximum sends per contact per day
maximum sends per campaign
unsubscribe handling
bounce handling
complaint handling
suppression list
market restriction
language selection
quiet-hours policy
safe-mode staging
```

No production mass campaign should activate merely because code was merged.

Use configuration + capability flag + environment approval.

---

# 42. LANGUAGE

All campaign templates must support:

```text
es-DO
en-US
```

Customer preferred language determines template.

Fallback:

```text
market default
```

Never send mixed-language templates.

---

# 43. TESTS — REQUIRED FOR `crm/odoo-campaign-core`

Codex must implement automated tests proving:

## Access

```text
customer agent cannot read another agent's private assigned customer
customer agent can read permitted unassigned queue
provider recruiter cannot read provider payout fields
partner agent cannot read unrelated customer profiles
supervisor can read supervised-user records
supervisor cannot read other supervisor team's records
marketing user cannot read restricted provider records
CRM manager cannot automatically read finance-restricted model
```

## Market Isolation

```text
DO-SDQ-only user cannot read DO-PUJ records
multi-market supervisor can read only assigned markets
```

## Projection

```text
duplicate event → one projection effect
older aggregate version → ignored/rejected
newer aggregate version → applied
unknown event type → recorded safely, no business mutation
malformed payload → failed integration event
```

## Security

```text
no direct write to booking projection by normal CRM users
restricted fields invisible without group
integration secret values never exposed in views
```

---

# 44. TESTS — CAMPAIGN MODULES

For every campaign:

```text
eligible customer enters once
ineligible customer does not enter
suppressed customer does not receive
booking completion exits appropriate flow
provider activation exits recruiting flow
language selects correct content
market rules honored
duplicate integration event does not duplicate participant
```

---

# 45. STAGING

Staging must use:

```text
separate Odoo database
separate credentials
separate LARIMÍA service identity
email safe mode
SMS allowlist
test partner accounts
test contacts
```

Never send production campaigns from staging.

---

# 46. OPERATIONS RECOVERY

Create Integration menu for Integration Admin:

```text
Integration Events
Failed Events
Retryable Events
Projection Lag
Provider Status
Last Successful Sync
```

Allowed:

```text
view
retry approved event
mark investigated
add internal note
```

Not allowed:

```text
edit marketplace booking directly
fabricate successful projection
delete audit evidence to hide failure
```

---

# 47. MENUS

Final navigation:

```text
LARIMÍA CRM
│
├── My Dashboard
│
├── Customers
│   ├── My Customers
│   ├── My Leads
│   ├── My Follow-ups
│   ├── Retention
│   └── Membership
│
├── Provider Recruitment
│   ├── My Candidates
│   ├── Applications
│   ├── Onboarding
│   └── Activation Follow-ups
│
├── Hotels & Corporate
│   ├── My Accounts
│   ├── Opportunities
│   ├── Proposals
│   ├── Active Partners
│   └── Renewal
│
├── Campaigns
│   ├── Active Campaigns
│   ├── Customer Lifecycle
│   ├── Provider Recruitment
│   ├── Hotel / Corporate
│   └── Results
│
├── Support
│   ├── My Cases
│   ├── Escalated Cases
│   └── Partner Issues
│
├── Reports
│   ├── Sales Funnel
│   ├── Retention
│   ├── Provider Recruitment
│   ├── Partner Pipeline
│   └── Campaign Performance
│
└── Integration
    ├── Events
    ├── Failures
    ├── Projection Status
    └── Configuration
```

Integration menu visible only to Integration Admin / approved managers.

---

# 48. CODEX IMPLEMENTATION RULES

Codex must follow these rules:

1. Inspect current repository before changing code.
2. Do not duplicate existing models/modules if equivalents exist.
3. Use current repository conventions.
4. Use normal Odoo ORM and security mechanisms.
5. Do not bypass ORM with direct SQL except justified migrations/reporting.
6. Do not use `sudo()` to bypass ordinary authorization.
7. Any required `sudo()` must be isolated, documented, and tested.
8. Do not make `res.partner` a dumping ground for sensitive projection data.
9. Do not expose secrets through views/logs/chatter.
10. Do not store LARIMÍA business truth in Odoo when a projection is sufficient.
11. Every inbound event must be idempotent.
12. Every outbound LARIMÍA command must use idempotency.
13. Add tests before marking a phase complete.
14. Never declare production-ready when staging/security/integration gates have not passed.

---

# 49. BRANCH / DELIVERY PLAN

Implement first branch:

```text
crm/odoo-campaign-core
```

Commit structure should preferably be:

```text
feat(crm): add larimia market and user security model
feat(crm): add customer and provider projections
feat(crm): add booking and partner projections
feat(crm): add crm lead extensions and stages
feat(crm): add groups and record rules
feat(crm): add core crm views and menus
feat(integration): add larimia projection event model
feat(integration): add larimia api client boundary
test(crm): add access and market isolation tests
test(integration): add projection idempotency tests
docs(crm): document campaign core
```

Do not squash away meaningful implementation boundaries until review if the team prefers commit-by-commit review.

---

# 50. DEFINITION OF DONE — `crm/odoo-campaign-core`

Do not mark the first phase complete until:

```text
module installs on clean Odoo database
module upgrades on existing test database
all access-right tests pass
all record-rule tests pass
market isolation passes
team isolation passes
restricted field tests pass
projection upsert passes
duplicate event idempotency passes
stale version handling passes
CRM menus render correctly
customer form renders correctly
provider form renders correctly
partner form renders correctly
booking projection is read-only to normal CRM
integration event queue visible to integration admin only
no direct LARIMÍA database dependency exists
outbound API client uses service boundary
lint/tests green
```

---

# 51. DEFINITION OF DONE — CUSTOMER CAMPAIGNS

After core is approved:

```text
new customer activation campaign implemented
abandoned quote campaign implemented
rebooking campaign implemented
membership campaign implemented
win-back campaign implemented

Spanish template path implemented
English template path implemented

consent rules enforced
suppression enforced
exit conditions tested
campaign attribution connected
booking deep links configured
```

---

# 52. DEFINITION OF DONE — PROVIDER CAMPAIGNS

```text
provider recruitment segmentation
recruitment nurture
application reminder
training reminder
activation exit
rejection exit
withdrawal exit
do-not-contact exit
market segmentation
service segmentation
```

---

# 53. DEFINITION OF DONE — PARTNER CAMPAIGNS

```text
hotel target-account pipeline
villa/property pipeline
corporate pipeline
event-planner pipeline
partner outreach campaigns
pilot stage
contracted stage
onboarding stage
renewal tracking
partner attribution
```

---

# 54. FINAL CODEX RESPONSE FORMAT

When Codex finishes `crm/odoo-campaign-core`, return:

```text
FINAL_STATUS=

BRANCH=
SOURCE_SHA=
ODOO_VERSION=

MODULES_ADDED=
MODULES_CHANGED=

MIGRATIONS=
INSTALL_TEST=
UPGRADE_TEST=

ACCESS_TESTS=
RECORD_RULE_TESTS=
MARKET_ISOLATION=
TEAM_ISOLATION=
FIELD_SECURITY=

CUSTOMER_PROJECTION=
PROVIDER_PROJECTION=
BOOKING_PROJECTION=
PARTNER_PROJECTION=

INBOUND_EVENT_IDEMPOTENCY=
STALE_EVENT_HANDLING=
OUTBOUND_API_CLIENT=

MENUS=
VIEWS=

KNOWN_BLOCKERS=
NEXT_SAFE_BRANCH=
```

If any mandatory test fails:

```text
FINAL_STATUS=PARTIAL
```

or:

```text
FINAL_STATUS=BLOCKED
```

Do not report production-ready unless all mandatory gates are actually proven.

---

# FIRST COMMAND TO CODEX

Use this exact implementation instruction:

> Read `docs/codex/ODOO_CAMPAIGN_CRM_IMPLEMENTATION.md` as the implementation authority. Inspect the repository first and preserve existing conventions. Implement **`crm/odoo-campaign-core` first and only**. Build the LARIMÍA CRM security foundation, market/team authorization, CRM-safe customer/provider/booking/partner projections, CRM lead extensions, pipeline stages, menus/views, integration event idempotency, LARIMÍA API-client boundary, and required automated tests. Do not implement later campaign automation branches until the core definition of done passes. Do not bypass security with broad `sudo()`, do not make Odoo marketplace authority, and do not call the work production-ready if any mandatory gate is unproven. Return the completion report in the exact format defined in this document.
