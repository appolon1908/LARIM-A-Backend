"""Explainable ranking over durable eligibility and cached, ephemeral coordinates."""

import json
from collections import Counter
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from larimia.config import get_settings

from . import domain
from .models import Block, Offer, Provider, now
from .models import MarketplaceBooking as Booking


class TravelEstimator(Protocol):
    def estimate(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict: ...


class LocalTravelEstimator:
    """Explicit approximation for unavailable map credentials, not live road/traffic ETA."""

    def estimate(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict:
        settings = get_settings()
        distance = domain.distance_km(*origin, *destination) * settings.dispatch_road_factor
        return {
            "distance_km": distance,
            "eta_minutes": distance / settings.dispatch_speed_kmh * 60,
            "travel_source": "local_estimate",
        }


def rank_candidates(
    db: Session,
    booking: Booking,
    excluded: set[UUID] | None = None,
    estimator: TravelEstimator | None = None,
) -> list[tuple[float, Provider, dict]]:
    from .service import eligible

    settings = get_settings()
    providers = db.scalars(
        select(Provider)
        .where(
            Provider.status == "APPROVED",
            Provider.online.is_(True),
            Provider.market_code == booking.snapshot["market_code"],
        )
        .order_by(Provider.id)
        .limit(1000)
    ).all()
    blocked = set(
        db.scalars(select(Block.provider_id).where(Block.customer_id == booking.customer_id))
    )
    candidates = [
        p
        for p in providers
        if p.id not in (excluded or set()) and eligible(db, p, booking, blocked)
    ]
    if not candidates:
        return []
    ids = [p.id for p in candidates]
    # Preaggregate history once, rather than querying each provider's offers.
    counts: dict[UUID, Counter] = {}
    recent: Counter = Counter()
    for provider_id, status, count in db.execute(
        select(Offer.provider_id, Offer.status, func.count())
        .where(Offer.provider_id.in_(ids), Offer.created_at >= now() - timedelta(days=30))
        .group_by(Offer.provider_id, Offer.status)
    ):
        counts.setdefault(provider_id, Counter())[status] = count
    for provider_id, count in db.execute(
        select(Offer.provider_id, func.count())
        .where(
            Offer.provider_id.in_(ids),
            Offer.status == "ACCEPTED",
            Offer.created_at >= now() - timedelta(hours=24),
        )
        .group_by(Offer.provider_id)
    ):
        recent[provider_id] = count
    service_key = Booking.snapshot["service_code"].as_string()
    demand: dict[str, int] = {
        code: count
        for code, count in db.execute(
            select(service_key, func.count())
            .where(
                Booking.status.in_(["SEARCHING", "OFFERED"]),
                Booking.snapshot["market_code"].as_string() == booking.snapshot["market_code"],
            )
            .group_by(service_key)
        ).all()
    }
    supply = Counter(service for p in providers if p.workload == 0 for service in p.services)
    positions = [None] * len(candidates)
    try:
        with Redis.from_url(
            settings.redis_url, socket_timeout=1, socket_connect_timeout=1
        ) as cache:
            positions = cache.mget(["larimia:location:" + str(p.id) for p in candidates])
    except RedisError:
        # Matching retains durable area coordinates when hot positions are temporarily unavailable.
        pass
    ranked = []
    travel = estimator or LocalTravelEstimator()
    for provider, position in zip(candidates, positions, strict=True):
        origin, location_source = (provider.latitude, provider.longitude), "service_area"
        if position:
            try:
                value = json.loads(position)
                latitude, longitude = float(value["latitude"]), float(value["longitude"])
                if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                    origin, location_source = (latitude, longitude), "redis_live"
            except (ValueError, KeyError, TypeError):
                pass
        details = travel.estimate(
            origin, (booking.address["latitude"], booking.address["longitude"])
        )
        history = counts.get(provider.id, Counter())
        responses = history["ACCEPTED"] + history["DECLINED"] + history["EXPIRED"]
        acceptance = (history["ACCEPTED"] + 1) / (responses + 2)
        scarcity = sum(
            demand.get(code, 0) / max(1, supply[code])
            for code in provider.services
            if code != booking.snapshot["service_code"]
        )
        rank = domain.score(
            details["distance_km"],
            provider.rating,
            provider.completion_rate,
            provider.workload,
            settings.dispatch_weights,
            eta_minutes=details["eta_minutes"],
            acceptance=acceptance,
            specialization=1 / max(1, len(provider.services)),
            recent_assignments=recent[provider.id],
            market_scarcity=scarcity,
        )
        details.update(
            location_source=location_source,
            acceptance_probability=acceptance,
            recent_assignments=recent[provider.id],
            market_scarcity=scarcity,
            specialization=1 / max(1, len(provider.services)),
            weights=settings.dispatch_weights,
        )
        ranked.append((rank, provider, details))
    return sorted(ranked, key=lambda row: (-row[0], str(row[1].id)))
