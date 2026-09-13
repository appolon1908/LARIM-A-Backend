# Dispatch and availability

Eligibility checks approval, online flag, services, required skills, market, UTC availability windows,
service radius, workload and blocked relationships. Blocking and offer history are preaggregated for
ranking rather than queried separately for every candidate. Atomic acceptance rechecks durable
eligibility while locking booking → provider → offer; exactly one provider can win.

Ranking considers distance, estimated arrival time, rating, completion rate, historical acceptance
probability, specialization, workload, recent assignments and competing demand for other services.
Weights are centralized, validated as finite/nonnegative and stored with each offer's ranking details.
Acceptance probability uses a smoothed 30-day offer history; fairness uses accepted offers over 24 hours.
Market balance discourages consuming multi-service capacity needed by other waiting services.

One Redis batch fetch retrieves fresh TTL-bound coordinates. If unavailable or invalid, durable service
area coordinates remain the fallback. TravelEstimator is injectable; LocalTravelEstimator labels its
geodesic/road-factor/average-speed estimate as `local_estimate`. It is not live road or traffic data.
Configure dispatch_speed_kmh and dispatch_road_factor centrally; live routing remains a vendor integration.

DispatchSession persists attempts; Offer persists score, ranking explanation, travel/location provenance,
expiry and status. The recovery worker excludes previously offered providers, expands offer batches,
and eventually records NO_PROVIDER_FOUND and releases mock authorization. Manual dispatch requires
booking.dispatch. Both initial dispatch and recovery use the same ranker. The candidate bound remains
1,000 per market; very large markets need spatial prefiltering before this bound.
