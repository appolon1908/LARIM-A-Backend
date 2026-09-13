from decimal import ROUND_HALF_UP, Decimal
from math import asin, cos, radians, sin, sqrt

STATES = {
    "DRAFT": {"QUOTED", "CANCELLED"},
    "QUOTED": {"PAYMENT_AUTHORIZED", "EXPIRED", "CANCELLED"},
    "PAYMENT_AUTHORIZED": {"SEARCHING", "CANCELLED"},
    "SEARCHING": {"OFFERED", "NO_PROVIDER_FOUND", "CANCELLED"},
    "OFFERED": {"ASSIGNED", "SEARCHING", "NO_PROVIDER_FOUND", "CANCELLED"},
    "ASSIGNED": {"PROVIDER_EN_ROUTE", "CANCELLED", "NO_SHOW"},
    "PROVIDER_EN_ROUTE": {"ARRIVED", "CANCELLED", "NO_SHOW"},
    "ARRIVED": {"IN_PROGRESS", "CANCELLED", "NO_SHOW"},
    "IN_PROGRESS": {"COMPLETED", "DISPUTED"},
    "COMPLETED": {"PAYMENT_CAPTURED", "DISPUTED"},
    "PAYMENT_CAPTURED": {"SETTLED", "DISPUTED", "REFUNDED", "PARTIALLY_REFUNDED"},
    "SETTLED": {"DISPUTED", "REFUNDED", "PARTIALLY_REFUNDED"},
    "DISPUTED": {"REFUNDED", "PARTIALLY_REFUNDED", "SETTLED"},
    "PARTIALLY_REFUNDED": {"REFUNDED", "PARTIALLY_REFUNDED"},
    "CANCELLED": set(),
    "EXPIRED": set(),
    "NO_PROVIDER_FOUND": set(),
    "NO_SHOW": set(),
    "REFUNDED": set(),
}


def transition(current: str, target: str) -> None:
    if target not in STATES.get(current, set()):
        raise ValueError(f"Booking cannot transition from {current} to {target}.")


def price(base: int, travel: int, tax_bps: int, fee_bps: int, discount: int = 0) -> dict:
    if min(base, travel, tax_bps, fee_bps, discount) < 0 or fee_bps > 10000:
        raise ValueError("Invalid pricing inputs")
    subtotal = base + travel
    if discount > subtotal:
        raise ValueError("Discount exceeds subtotal")
    taxable = subtotal - discount
    tax = int((Decimal(taxable) * tax_bps / 10000).quantize(Decimal("1"), ROUND_HALF_UP))
    fee = int((Decimal(base) * fee_bps / 10000).quantize(Decimal("1"), ROUND_HALF_UP))
    if discount >= base - fee + travel:
        raise ValueError("Discount must preserve positive provider earnings")
    return dict(
        base_minor=base,
        travel_minor=travel,
        discount_minor=discount,
        tax_minor=tax,
        platform_fee_minor=fee,
        total_minor=taxable + tax,
        provider_earning_minor=base - fee + travel - discount,
    )


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(min(1, sqrt(a)))


def score(
    distance: float,
    rating: float,
    completion: float,
    workload: int,
    weights: dict[str, float],
    *,
    eta_minutes: float = 0,
    acceptance: float = 0,
    specialization: float = 0,
    recent_assignments: int = 0,
    market_scarcity: float = 0,
) -> float:
    return (
        weights["distance"] / (1 + distance)
        + weights["rating"] * rating / 5
        + weights["completion"] * completion
        - weights["workload"] * workload
        + weights.get("eta", 0) / (1 + eta_minutes)
        + weights.get("acceptance", 0) * acceptance
        + weights.get("specialization", 0) * specialization
        - weights.get("fairness", 0) * recent_assignments
        - weights.get("market_balance", 0) * market_scarcity
    )


def balanced(entries: list[tuple[str, str, int]]) -> None:
    if len(entries) < 2 or any(v <= 0 or d not in {"DEBIT", "CREDIT"} for _, d, v in entries):
        raise ValueError("Invalid ledger entries")
    if sum(v if d == "DEBIT" else -v for _, d, v in entries) != 0:
        raise ValueError("Ledger transaction does not balance")
