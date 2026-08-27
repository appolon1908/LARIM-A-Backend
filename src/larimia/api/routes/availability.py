from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from larimia.marketplace.capacity import CapacityService
from larimia.shared.db import get_db


router = APIRouter()


@router.get("")
def availability(
    market: str = Query(min_length=1, max_length=16),
    service_code: str = Query(min_length=1, max_length=80),
    from_time: datetime = Query(),
    days: int = Query(1, ge=1, le=14),
    db: Session = Depends(get_db),
):
    return {
        "market": market,
        "service_code": service_code,
        "slots": CapacityService.slots(
            db,
            service_code=service_code,
            market_code=market,
            from_time=from_time,
            days=days,
        ),
    }
