from datetime import datetime
from fastapi import APIRouter,Depends,Query
from sqlalchemy.orm import Session
from larimia.marketplace.services import AvailabilityService
from larimia.shared.db import get_db
router=APIRouter()
@router.get("")
def availability(market:str,service_code:str,from_time:datetime,days:int=Query(1,ge=1,le=7),db:Session=Depends(get_db)):
    return {"market":market,"service_code":service_code,"slots":AvailabilityService.slots(db,service_code=service_code,market_code=market,from_time=from_time,days=days)}
