# Pricing

Catalog stores server-controlled base price, travel charge, tax basis points, commission basis points
and a version. A quote validates service/market/currency, owned address and future schedule, computes
minor-unit amounts with Decimal ROUND_HALF_UP, and expires after ten minutes. Unknown services do not
fall back to an invented price. Unsupported add-ons are explicitly rejected rather than silently free.

Promotion eligibility checks code, currency, active state and expiry. Discounts cannot erase provider
earnings. The accepted quote snapshots all amounts, service requirements, currency and rule version.
Admin rule changes only affect subsequent quotes, verified by an integration regression.

Provider earnings are computed separately from customer total. The current catalog implements fixed
base/travel pricing; urgency, dynamic demand, memberships, arbitrary add-ons and per-distance pricing
are not presented as completed features. Their future implementation must extend the pricing service,
not accept client totals.
