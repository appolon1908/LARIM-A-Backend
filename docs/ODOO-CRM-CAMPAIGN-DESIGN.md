Below is the Odoo CRM/campaign architecture I recommend for LARIMÍA. It follows the production blueprint you provided: the **LARIMÍA backend remains the business source of truth**, while Odoo acts as the CRM, campaign, sales, partner, and selected support projection layer. 

Odoo 19 gives us the right building blocks for this: CRM, Sales Teams, Marketing Automation, Email Marketing, Contacts, Documents, Dashboards, user groups, model access rights, and record rules. Odoo’s current security model separates model-level CRUD access from record rules that restrict which actual records a user can see or modify. 

# LARIMÍA Odoo CRM Design

## 1. Odoo's role in the platform

```
```

```
                    LARIMÍA CORE
              Python / FastAPI / PostgreSQL
                         │
                 Domain Events / API
                         │
                         ▼
               Integration Control Plane
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         Odoo CRM             Marketing / Comms
              │
     ┌────────┼─────────┐
     ▼        ▼         ▼
 Customer   Provider   Partner
   CRM        CRM       CRM
     │        │         │
 Campaigns  Recruiting  Hotels
 Retention  Activation  Corporate
 Win-back   Quality     Events
```

### LARIMÍA remains authoritative for

```
```

```
booking state
provider availability
matching
dispatch
provider eligibility
credentials
visit state
safety state
customer payments
provider payouts
ledger/accounting truth
membership entitlement
service availability
```

### Odoo may own

```
```

```
CRM lead lifecycle
customer relationship activity
partner/hotel sales pipeline
corporate sales
provider recruitment pipeline
campaign membership
marketing automation
sales calls/tasks
CRM notes
approved support summaries
campaign attribution
partner contracts/proposals
CRM dashboards
```

Odoo must **never directly update LARIMÍA PostgreSQL**. Any action that changes marketplace truth goes back through an approved LARIMÍA command API, as required by your integration blueprint. 

---

# 2. Recommended Odoo applications/modules

Install these standard applications:

| ModulePurpose        |                                              |
| -------------------- | -------------------------------------------- |
| CRM                  | Leads, opportunities, pipelines              |
| Contacts             | Customer/provider/partner contacts           |
| Sales                | Hotel/corporate proposals and contracts      |
| Marketing Automation | Lifecycle campaigns                          |
| Email Marketing      | Campaign delivery                            |
| SMS Marketing        | Optional lifecycle SMS                       |
| Discuss              | Internal team collaboration                  |
| Calendar             | Calls, partner meetings, onboarding          |
| Documents            | Contracts, approved CRM documents            |
| Sign                 | Partner/provider documents where appropriate |
| Helpdesk             | CRM-level customer/partner support           |
| Dashboards           | Executive/team KPI views                     |
| Knowledge            | SOPs, scripts, campaign playbooks            |

Odoo Marketing Automation supports campaigns against target models such as contacts or leads/opportunities and uses filtered records as campaign participants. 

I would also build **one custom LARIMÍA Odoo addon**:

```
```

```
larimia_crm/
├── models/
│   ├── crm_lead.py
│   ├── res_partner.py
│   ├── larimia_booking_projection.py
│   ├── larimia_provider_projection.py
│   ├── larimia_partner_account.py
│   ├── larimia_campaign_attribution.py
│   └── larimia_integration_event.py
│
├── security/
│   ├── groups.xml
│   ├── ir.model.access.csv
│   └── record_rules.xml
│
├── views/
│   ├── crm_lead_views.xml
│   ├── customer_views.xml
│   ├── provider_views.xml
│   ├── partner_views.xml
│   ├── booking_projection_views.xml
│   └── dashboard_views.xml
│
├── data/
│   ├── stages.xml
│   ├── activities.xml
│   └── automation.xml
│
└── controllers/
    └── larimia_api.py
```

---

# 3. CRM menu layout

I would make the Odoo navigation very simple for agents.

```
```

```
LARIMÍA CRM
│
├── My Dashboard
│
├── Customers
│   ├── My Customers
│   ├── My Leads
│   ├── My Follow-ups
│   ├── Retention Opportunities
│   └── VIP / Membership
│
├── Provider Recruitment
│   ├── My Candidates
│   ├── Applications
│   ├── Onboarding Pipeline
│   └── Activation Follow-ups
│
├── Hotels & Corporate
│   ├── My Accounts
│   ├── Opportunities
│   ├── Proposals
│   ├── Active Partners
│   └── Renewal Pipeline
│
├── Campaigns
│   ├── Active Campaigns
│   ├── Customer Lifecycle
│   ├── Provider Recruitment
│   ├── Hotel / Corporate
│   └── Campaign Results
│
├── Support
│   ├── My Cases
│   ├── Escalated Cases
│   └── Partner Issues
│
└── Reports
    ├── Sales Funnel
    ├── Customer Retention
    ├── Provider Recruitment
    ├── Partner Pipeline
    └── Campaign Performance
```

Supervisors receive additional menus:

```
```

```
Supervisor
├── Team Dashboard
├── Team Leads
├── Team Customers
├── Team Activities
├── Unassigned Leads
├── SLA Breaches
├── Campaign Performance
├── Agent Performance
└── Reassignment
```

Managers receive:

```
```

```
Management
├── All Teams
├── Markets
├── Campaign Configuration
├── Pipeline Configuration
├── Reporting
└── Integration Status
```

---

# 4. Separate CRM pipelines

Do not put every person into one pipeline.

## A. Customer acquisition

```
```

```
NEW
 ↓
CONTACT ATTEMPTED
 ↓
QUALIFIED
 ↓
BOOKING INTENT
 ↓
FIRST BOOKING
 ↓
ACTIVATED
```

Loss reasons:

```
```

```
no response
price
service unavailable
outside service zone
not ready
duplicate
bad contact
```

---

## B. Customer retention

```
```

```
ACTIVE
 ↓
REBOOK OPPORTUNITY
 ↓
CONTACTED
 ↓
OFFER PRESENTED
 ↓
REBOOKED
```

Alternative:

```
```

```
AT RISK
 ↓
RECOVERY
 ↓
RETAINED
```

or

```
```

```
CHURNED
```

---

# 5. Provider recruitment pipeline

```
```

```
NEW CANDIDATE
       ↓
CONTACTED
       ↓
INTERESTED
       ↓
APPLICATION STARTED
       ↓
APPLICATION SUBMITTED
       ↓
VERIFICATION
       ↓
TRAINING / ASSESSMENT
       ↓
READY FOR ACTIVATION
       ↓
ACTIVATED
```

Odoo tracks the recruitment relationship.

LARIMÍA backend decides:

```
```

```
identity verified?
credential valid?
background check valid?
skills approved?
kit approved?
market eligible?
```

Odoo can display those statuses, but cannot change them directly.

---

# 6. Hotel / villa / corporate pipeline

This should be a proper B2B pipeline.

```
```

```
TARGET ACCOUNT
      ↓
CONTACT IDENTIFIED
      ↓
DISCOVERY
      ↓
QUALIFIED
      ↓
DEMO / PROPOSAL
      ↓
COMMERCIAL NEGOTIATION
      ↓
LEGAL / PROCUREMENT
      ↓
CONTRACTED
      ↓
ONBOARDING
      ↓
LIVE
```

Renewal pipeline:

```
```

```
ACTIVE
 ↓
90-DAY REVIEW
 ↓
RENEWAL DISCUSSION
 ↓
RENEWED
```

or:

```
```

```
AT RISK
```

---

# 7. Customer CRM profile layout

I would design the customer form like this:

```
```

```
┌──────────────────────────────────────────────────────┐
│ María Rodríguez                   CUSTOMER · ACTIVE  │
│ Santo Domingo · Spanish · Member                    │
├──────────────────────────────────────────────────────┤
│ CRM OWNER          Carlos M.                         │
│ CUSTOMER SINCE     2026-09-11                        │
│ LIFETIME BOOKINGS  7                                 │
│ LAST SERVICE       Massage                           │
│ NEXT BOOKING       Sep 28 · 4:00 PM                  │
│ MEMBERSHIP         LARIMÍA Plus                      │
├──────────────────────────────────────────────────────┤
│ Overview | Activity | Bookings | Campaigns | Support │
├──────────────────────────────────────────────────────┤
│ Contact Details                                      │
│ Preferred language                                   │
│ Preferred channel                                    │
│ Market                                               │
│ Customer segment                                     │
│ Campaign source                                      │
│ First-touch source                                   │
│ Last-touch source                                    │
│                                                      │
│ CRM NOTES                                             │
│ [approved business notes only]                       │
└──────────────────────────────────────────────────────┘
```

### Do not expose to ordinary CRM users

```
```

```
full payment information
payment tokens
provider exact live GPS
customer safety reports
private incident evidence
background-check data
ledger details
internal risk flags
sensitive health information
raw identity documents
authentication information
```

---

# 8. Provider CRM profile

```
```

```
┌─────────────────────────────────────────────────────┐
│ Ana Gómez                 PROVIDER · ACTIVE          │
│ Massage · Makeup          Santo Domingo              │
├─────────────────────────────────────────────────────┤
│ RECRUITER           José                             │
│ ACTIVATED           Aug 12                           │
│ SERVICES            Massage / Makeup                 │
│ CRM QUALITY BAND    Excellent                        │
│ STATUS              Active                           │
├─────────────────────────────────────────────────────┤
│ Recruitment | Activity | Eligibility | Training     │
│ Campaigns   | Notes    | CRM Timeline                │
└─────────────────────────────────────────────────────┘
```

Projection fields can include:

```
```

```
Provider ID
market
services
activation status
credential summary: valid / expiring / blocked
training status
quality band
last active date
completed service count
```

But Odoo should not expose raw credential documents to ordinary recruiters.

---

# 9. Campaign architecture

I recommend six customer campaign families.

## Campaign 1 — New customer activation

Trigger:

```
```

```
account created
AND
no booking after 2 hours
```

Sequence:

```
```

```
2h → welcome
24h → service discovery
72h → social proof / convenience
7d → first-booking reminder
```

Exit:

```
```

```
booking confirmed
unsubscribe
suppressed
```

---

## Campaign 2 — Abandoned booking

Trigger:

```
```

```
quote created
AND
not confirmed
```

Sequence:

```
```

```
30 min → reminder
24h → service reminder
48h → final follow-up
```

Agents should see:

```
```

```
quote value
service
market
campaign
customer
```

but not payment failure internals.

---

# 10. Customer rebooking campaign

Trigger:

```
```

```
completed booking
+
expected rebook window reached
```

Different windows by service:

```
```

```
Haircut          ~ 3–6 weeks
Massage          configurable
Makeup           event-driven
Personal training recurring
Hair styling     event / recurring
```

CRM action:

```
```

```
campaign message
        ↓
customer clicks
        ↓
booking deep link
```

Booking occurs in LARIMÍA, not Odoo.

---

# 11. Membership campaign

Segments:

```
```

```
frequent customers
high lifetime spend
repeat customers
multi-category customers
hotel/villa customers
```

Campaign:

```
```

```
Membership Eligible
        ↓
Benefits Education
        ↓
Offer
        ↓
Membership Signup
```

Odoo receives the resulting membership status as a projection.

---

# 12. Win-back campaign

Trigger:

```
```

```
previously active
AND
no completed booking for X days
```

Segments:

```
```

```
30-day inactive
60-day inactive
90-day inactive
high-value churn risk
```

Avoid aggressive discounting automatically.

Use:

```
```

```
personal reminder
favorite category
previous professional if available
membership benefit
service discovery
```

---

# 13. Provider recruitment campaigns

Segments:

```
```

```
massage professionals
barbers
hair stylists
makeup artists
personal trainers
Punta Cana candidates
Santo Domingo candidates
```

Sequence:

```
```

```
Lead
 ↓
Recruitment message
 ↓
Benefits
 ↓
Application link
 ↓
Application reminder
 ↓
Training reminder
```

Stop automation when:

```
```

```
activated
rejected
withdrawn
do-not-contact
```

---

# 14. Hotel campaign

Segments:

```
```

```
luxury hotels
boutique hotels
villa managers
property management companies
wedding/event planners
corporate wellness
```

Campaign stages:

```
```

```
Introduction
      ↓
Concierge use case
      ↓
Meeting
      ↓
Pilot proposal
      ↓
Partnership
```

Track:

```
```

```
rooms
property type
market
guest volume
spa availability
concierge contact
decision maker
contract value
pilot status
```

---

# 15. Agent roles

I recommend these custom groups.

```
```

```
LARIMÍA CRM / Customer Agent

LARIMÍA CRM / Provider Recruiter

LARIMÍA CRM / Partner Sales Agent

LARIMÍA CRM / Support Agent

LARIMÍA CRM / Supervisor

LARIMÍA CRM / CRM Manager

LARIMÍA CRM / Marketing Manager

LARIMÍA CRM / Integration Administrator
```

Odoo supports group-based model access plus separate record rules for restricting individual records. 

---

# 16. Customer agent visibility

### Can see

```
```

```
assigned leads
assigned customers
unassigned leads in their permitted queue
customer contact information
market
language
service interests
booking summaries
membership summary
campaign participation
CRM conversation history
support summary
activities/tasks
approved retention offers
```

### Can change

```
```

```
lead stage
CRM notes
follow-up date
communication preference where authorized
campaign disposition
loss reason
activity
lead ownership only if queue rules permit
```

### Cannot see

```
```

```
other agents' private leads
provider financial information
provider payout amounts
platform financial reports
safety incidents
identity documents
background checks
customer payment instruments
ledger
integration credentials
staff audit log
```

---

# 17. Provider recruiter visibility

### Can see

```
```

```
assigned provider candidates
contact details
requested services
market
application progress
high-level verification result
training progress
activation readiness
CRM correspondence
```

### Cannot see

```
```

```
full background-check report
raw government ID
bank account
payout account
customer complaints marked safety-restricted
financial ledger
provider earnings unless specifically authorized
```

---

# 18. Partner sales visibility

### Can see

```
```

```
assigned hotels/corporate accounts
contacts
pipeline
meeting notes
proposals
contract status
booking volume summaries
partner invoices summary
```

### Cannot see

```
```

```
consumer customer list outside partner-linked bookings
provider identity beyond business need
safety incidents
payment tokens
provider payout data
other sales territories unless granted
```

---

# 19. Supervisor visibility

A supervisor should see the **team**, not necessarily the entire organization.

### Can see

```
```

```
own records
records belonging to supervised agents
team unassigned queue
team campaigns
team activities
team performance
team SLA breaches
team pipeline
```

### Can do

```
```

```
assign/reassign leads
approve limited credits/offers
review agent notes
review calls/tasks
close stale leads
escalate support
approve campaign exceptions
```

### Cannot automatically see

```
```

```
other supervisors' teams
executive financial data
restricted safety incidents
payment credentials
integration secrets
raw verification documents
audit/security configuration
```

This is exactly where Odoo record rules are important. Odoo's own developer documentation uses record rules for the same pattern: agents see their own records while managers can see broader sets. 

---

# 20. CRM manager visibility

CRM Manager:

```
```

```
all customer CRM
all provider recruitment CRM
all partner pipeline
campaign results
sales-team configuration
lead assignment
CRM reporting
```

But even CRM Manager should **not** automatically have:

```
```

```
platform administrator
safety administrator
finance administrator
technical Odoo administrator
```

Those are separate responsibilities.

---

# 21. Marketing manager

Marketing Manager can:

```
```

```
create campaigns
define audiences
create templates
schedule campaigns
view aggregate performance
manage UTM taxonomy
manage segments
run A/B tests
```

Cannot automatically:

```
```

```
open private safety cases
view raw identity documents
view full provider payout records
modify marketplace booking state
manually assign providers
```

---

# 22. Example record rules

For Customer Agents:

```
```

```
[
    '|',
    ('user_id', '=', user.id),
    ('user_id', '=', False)
]
```

Meaning:

```
```

```
my assigned leads
OR
unassigned leads
```

For Supervisor:

```
```

```
[
    '|',
    ('user_id', '=', user.id),
    ('user_id', 'in', user.larimia_team_member_ids.ids)
]
```

For market restriction:

```
```

```
[
    ('larimia_market_code', 'in', user.larimia_market_codes)
]
```

Combine them carefully:

```
```

```
allowed market
AND
(
    mine
    OR
    my team's
    OR
    permitted unassigned queue
)
```

Odoo record rules are evaluated after model access rights and restrict the records an operation can act on. They are default-allow if access is granted and no applicable rule restricts the record, so you should deliberately define the required rules rather than assuming hidden menus provide security. 

---

# 23. Recommended permissions matrix

| ResourceAgentSupervisorCRM ManagerMarketingAdmin |               |                 |         |                 |                       |
| ------------------------------------------------ | ------------- | --------------- | ------- | --------------- | --------------------- |
| Own leads                                        | RW            | RW              | RW      | R               | RW                    |
| Team leads                                       | —             | RW              | RW      | R               | RW                    |
| All CRM leads                                    | —             | —               | RW      | R\*             | RW                    |
| Customer contact                                 | R/W limited   | RW              | RW      | R limited       | RW                    |
| Provider candidates                              | role-specific | team            | RW      | R campaign only | RW                    |
| Campaigns                                        | R             | R               | R       | RW              | RW                    |
| Send campaign                                    | —             | approve limited | approve | RW              | RW                    |
| Partner opportunities                            | assigned      | team            | RW      | R               | RW                    |
| Booking projection                               | R             | R               | R       | aggregate       | RW                    |
| Payment projection                               | —             | —               | summary | —               | limited               |
| Safety incidents                                 | —             | restricted      | —       | —               | separate safety role  |
| Ledger                                           | —             | —               | —       | —               | separate finance role |
| Integration config                               | —             | —               | —       | —               | Integration Admin     |
| User/security config                             | —             | —               | —       | —               | Odoo Admin            |

`R*` means only campaign-relevant fields; sensitive/private fields should be hidden through model separation or field groups, not merely views.

Odoo allows field-level group restrictions in addition to model access and record rules. 

---

# 24. Dashboard layout

## Agent dashboard

```
```

```
┌────────────┬────────────┬────────────┬────────────┐
│ New Leads  │ Due Today  │ Follow-ups │ Booked     │
│     18     │     11     │      7     │     5      │
└────────────┴────────────┴────────────┴────────────┘

MY PIPELINE

New        Contacted      Qualified       Booking
 8             11             6              5

TODAY
09:00 Call Maria
10:30 Follow up Hotel X
11:15 New membership lead

MY CAMPAIGNS
First Booking       12 active
Win Back             8 active
Membership           4 active
```

---

# 25. Supervisor dashboard

```
```

```
Team conversion
Lead response SLA
Leads per agent
Bookings generated
Pipeline aging
Unassigned records
Overdue activities
Campaign conversion
Lost reasons
Agent workload
```

Avoid ranking agents solely on raw revenue.

Include:

```
```

```
response speed
follow-up completion
customer conversion
quality
complaint/escalation rate
retention
```

---

# 26. Executive CRM dashboard

```
```

```
Acquisition
├── leads
├── qualified
├── first bookings
├── CAC source
└── conversion

Retention
├── repeat booking
├── reactivation
├── churn
└── membership

Providers
├── recruited
├── applications
├── activation
└── time-to-activate

B2B
├── hotel pipeline
├── contracts
├── pilot conversion
└── booking volume

Campaign
├── delivered
├── engagement
├── booking attribution
├── reactivation
└── revenue contribution
```

Odoo dashboards respect model access rights and record rules when rendering underlying data, so supervisors can use common dashboard definitions while only seeing records they are authorized to see. 

---

# 27. LARIMÍA → Odoo event mapping

Use events such as:

```
```

```
customer.created.v1
       → create/update contact

customer.first_booking_completed.v1
       → activate customer CRM

booking.completed.v1
       → update last-service projection
       → evaluate rebooking campaign

membership.started.v1
       → update membership CRM field

provider.application_started.v1
       → provider candidate

provider.activated.v1
       → close recruitment opportunity

partner.created.v1
       → create partner account

partner.booking_completed.v1
       → update B2B activity

customer.support_escalated.v1
       → optional approved CRM support projection
```

---

# 28. Odoo → LARIMÍA commands

Only explicitly allowlisted actions:

```
```

```
request customer follow-up notification

create partner booking request

create approved promotion assignment

request provider recruitment invitation

create support case

request callback
```

Never permit:

```
```

```
UPDATE booking status

assign provider directly

activate provider directly

change credential validity

capture payment

refund payment

change ledger

change payout balance
```

Those commands belong to LARIMÍA's authoritative domain.

---

# 29. Sensitive data partitioning

I would create separate projection models instead of putting everything on `res.partner`.

For example:

```
```

```
res.partner
    normal CRM identity

larimia.customer.profile
    CRM-safe customer projection

larimia.provider.profile
    CRM-safe provider projection

larimia.booking.projection
    safe booking summary

larimia.integration.event
    integration tracking

larimia.partner.account
    hotel/corporate CRM
```

This makes permissions much cleaner than trying to hide fifty sensitive fields on Contacts.

---

# 30. Final recommended Odoo architecture

```
```

```
Odoo 19

CRM
├── Customer Acquisition
├── Customer Retention
├── Provider Recruitment
└── Hotel / Corporate Sales

Marketing Automation
├── New Customer
├── Abandoned Quote
├── Rebooking
├── Win Back
├── Membership
├── Provider Recruitment
└── Hotel Outreach

Helpdesk
├── General CRM Support
└── Partner Support

Documents / Sign
├── Partner Contracts
└── Approved Provider Documents

Dashboards
├── Agent
├── Supervisor
├── CRM Management
├── Marketing
└── Executive

Custom LARIMÍA Module
├── CRM Projections
├── Marketplace IDs
├── Market Security
├── Team Security
├── Integration Events
├── Campaign Attribution
├── Role Groups
├── Record Rules
└── LARIMÍA API Adapter
```

The main security rule is:

> **Agents see only their assigned records and permitted unassigned queues. Supervisors see their team. Managers see their functional area. Sensitive safety, finance, identity, payment, and integration data remain in separate roles and preferably separate models.**

That gives you CRM visibility without turning Odoo into a back door around the permissions enforced by the LARIMÍA marketplace.