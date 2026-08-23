import uuid
from datetime import datetime
from fastapi import APIRouter,Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from larimia.marketplace.services import QuoteService
from larimia.shared.auth import Principal,get_principal
from larimia.shared.authorization import customer_for_principal,require_market
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import reserve,complete
router=APIRouter()
class QuoteRequest(BaseModel):
    market_code:str;service_code:str;address_id:uuid.UUID;scheduled_start:datetime
@router.post("",status_code=201)
def create(payload:QuoteRequest,key:str=Depends(require_idempotency_key),principal:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    c=customer_for_principal(db,principal);require_market(principal,payload.market_code)
    idem,replay=reserve(db,actor_subject=principal.subject,operation="quote.create",key=key,payload=payload.model_dump())
    if replay is not None:return replay
    q=QuoteService.create(db,customer=c,**payload.model_dump())
    result={"id":str(q.id),"status":q.status,"market_code":q.market_code,"currency":q.currency,"subtotal_minor":q.subtotal_minor,"tax_minor":q.tax_minor,"total_minor":q.total_minor,"scheduled_start":q.scheduled_start.isoformat(),"scheduled_end":q.scheduled_end.isoformat(),"expires_at":q.expires_at.isoformat(),"price_policy_version":q.price_policy_version}
    complete(db,idem,result);db.commit();return result
