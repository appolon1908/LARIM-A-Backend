import json
from datetime import timedelta
from uuid import uuid4

from redis import Redis

from larimia.config import get_settings
from larimia.marketplace.dispatch_ranking import rank_candidates
from larimia.marketplace.models import MarketplaceBooking, Provider, User, now
from larimia.shared.db import SessionLocal


def test_hot_position_ranking_and_durable_fallback():
    market = uuid4().hex[:12]
    start, end = now() + timedelta(days=1), now() + timedelta(days=1, hours=1)
    ids = []
    with SessionLocal.begin() as db:
        for _ in range(2):
            user = User(subject=str(uuid4()), email=str(uuid4()) + "@example.test")
            db.add(user)
            db.flush()
            provider = Provider(
                user_id=user.id,
                status="APPROVED",
                online=True,
                services=["test"],
                skills=["test"],
                market_code=market,
                latitude=18.4,
                longitude=-69.9,
                radius_km=30,
                availability=[{"start": start.isoformat(), "end": end.isoformat()}],
            )
            db.add(provider)
            db.flush()
            ids.append(provider.id)
    booking = MarketplaceBooking(
        customer_id=uuid4(),
        scheduled_start=start,
        scheduled_end=end,
        snapshot={"market_code": market, "service_code": "test", "required_skills": ["test"]},
        address={"latitude": 18.5, "longitude": -69.9},
    )
    key = "larimia:location:" + str(ids[1])
    with Redis.from_url(get_settings().redis_url) as redis:
        redis.setex(key, 120, json.dumps({"latitude": 18.5, "longitude": -69.9}))
        try:
            with SessionLocal() as db:
                ranked = rank_candidates(db, booking)
                assert ranked[0][1].id == ids[1]
                assert ranked[0][2]["location_source"] == "redis_live"
                assert ranked[0][2]["travel_source"] == "local_estimate"
                assert ranked[0][2]["acceptance_probability"] == 0.5
                assert len(rank_candidates(db, booking, {ids[1]})) == 1
            redis.delete(key)
            with SessionLocal() as db:
                ranked = rank_candidates(db, booking)
                assert all(item[2]["location_source"] == "service_area" for item in ranked)
        finally:
            redis.delete(key)
