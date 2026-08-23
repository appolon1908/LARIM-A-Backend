from fastapi import APIRouter,Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from larimia.marketplace.models import Service,PricePolicy
from larimia.shared.db import get_db
router=APIRouter()
@router.get("")
def catalog(market:str="DO-SDQ",db:Session=Depends(get_db)):
    rows=list(db.execute(select(Service,PricePolicy).join(PricePolicy,PricePolicy.service_id==Service.id).where(Service.active.is_(True),PricePolicy.active.is_(True),PricePolicy.market_code==market).order_by(Service.category,Service.code)))
    return {"market":market,"services":[{"id":str(s.id),"code":s.code,"category":s.category,"name":{"es-DO":s.name_es,"en-US":s.name_en},"duration_minutes":s.duration_minutes,"currency":p.currency,"base_price_minor":p.base_price_minor,"price_policy_version":p.version} for s,p in rows]}
