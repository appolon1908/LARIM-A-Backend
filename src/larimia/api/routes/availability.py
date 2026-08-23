from datetime import datetime, timedelta, timezone
from fastapi import APIRouter

router = APIRouter()

@router.get("")
def availability(market: str, service_code: str, date: str, address_id: str):
    # Contract-complete stub. Replace generated slots with provider + routing-backed query.
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    return {
        "market": market,
        "service_code": service_code,
        "address_id": address_id,
        "slots": [
            {"start": (now + timedelta(hours=i)).isoformat(), "available": True}
            for i in range(5)
        ],
    }
