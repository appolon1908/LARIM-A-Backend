# Dispatch and availability

Eligibility checks approval, online flag, service, required skills, market, UTC availability window,
service radius, current workload and blocked relationships. Ranking combines distance, rating,
completion rate and workload penalties using centralized settings. Distance is a local geodesic
estimate, not a certified road ETA. Dedicated routing/ETA vendor integration remains optional.

A persisted DispatchSession owns attempts; Offer owns provider, score, expiry and state. Acceptance
locks booking → provider → offer, checks current version/expiry/eligibility, assigns exactly one
provider and cancels remaining offers. Independent concurrent requests are tested against PostgreSQL.

The recovery worker expires pending batches, excludes previously offered providers, tries another
batch and eventually records NO_PROVIDER_FOUND and releases mock authorization. No Redis lock is the
sole assignment authority. Manual dispatch is protected by booking.dispatch. Candidate queries are
bounded at 1,000 records; large-market spatial prefiltering and richer fairness/acceptance modeling
remain scaling work. Current dispatch uses durable service-area coordinates; Redis live location is
separate and does not yet provide road-routing precision.
