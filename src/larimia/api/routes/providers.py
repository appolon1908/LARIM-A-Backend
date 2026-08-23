import uuid
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from larimia.marketplace.models import Provider,ProviderService,Service,AvailabilityRule
from larimia.shared.auth import Principal,Role,get_principal,require_roles
from larimia.shared.authorization import provider_for_principal,require_market
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import reserve,complete
router=APIRouter()

class Application(BaseModel):
    display_name:str;market_code:str;requested_services:list[str]
class Availability(BaseModel):
    weekday:int;start_minute:int;end_minute:int;timezone:str

@router.post("/applications",status_code=201)
def apply(payload:Application,key:str=Depends(require_idempotency_key),p:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    require_market(p,payload.market_code)
    idem,replay=reserve(db,actor_subject=p.subject,operation="provider.apply",key=key,payload=payload.model_dump())
    if replay is not None:return replay
    row=db.scalar(select(Provider).where(Provider.identity_issuer==p.issuer,Provider.identity_subject==p.subject))
    if not row:
        row=Provider(identity_issuer=p.issuer,identity_subject=p.subject,market_code=payload.market_code,status="APPLICANT",onboarding_status="APPLICATION_SUBMITTED",display_name=payload.display_name,version=1,created_at=datetime.now(timezone.utc));db.add(row);db.flush()
        services=list(db.scalars(select(Service).where(Service.code.in_(payload.requested_services))))
        for s in services:db.add(ProviderService(provider_id=row.id,service_id=s.id,status="PENDING"))
    result={"id":str(row.id),"status":row.status,"onboarding_status":row.onboarding_status};complete(db,idem,result);db.commit();return result

@router.get("/application-status")
def application_status(p:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    row=db.scalar(select(Provider).where(Provider.identity_issuer==p.issuer,Provider.identity_subject==p.subject))
    if not row:raise HTTPException(404,detail={"code":"APPLICATION_NOT_FOUND"})
    return {"id":str(row.id),"status":row.status,"onboarding_status":row.onboarding_status,"market_code":row.market_code}

@router.get("/me")
def me(p:Principal=Depends(require_roles(Role.PROVIDER)),db:Session=Depends(get_db)):
    row=provider_for_principal(db,p);return {"id":str(row.id),"display_name":row.display_name,"status":row.status,"market_code":row.market_code,"version":row.version}

@router.put("/me/availability")
def availability(rules:list[Availability],key:str=Depends(require_idempotency_key),p:Principal=Depends(require_roles(Role.PROVIDER)),db:Session=Depends(get_db)):
    provider=provider_for_principal(db,p);idem,replay=reserve(db,actor_subject=p.subject,operation="provider.availability",key=key,payload=[r.model_dump() for r in rules])
    if replay is not None:return replay
    db.execute(delete(AvailabilityRule).where(AvailabilityRule.provider_id==provider.id))
    for r in rules:db.add(AvailabilityRule(provider_id=provider.id,active=True,**r.model_dump()))
    result={"updated":True,"count":len(rules)};complete(db,idem,result);db.commit();return result
