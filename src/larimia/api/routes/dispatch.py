import uuid
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import BookingLine,DispatchOffer
from larimia.marketplace.services import DispatchService
from larimia.shared.auth import Principal,Role,require_roles
from larimia.shared.authorization import provider_for_principal,require_market
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import reserve,complete
router=APIRouter()
class AcceptOffer(BaseModel): booking_version:int

@router.post("/ops/bookings/{booking_id}/offers")
def create_offers(booking_id:uuid.UUID,key:str=Depends(require_idempotency_key),principal:Principal=Depends(require_roles(Role.DISPATCHER)),db:Session=Depends(get_db)):
    idem,replay=reserve(db,actor_subject=principal.subject,operation="dispatch.create_offers",key=key,payload={"booking_id":str(booking_id)})
    if replay is not None:return replay
    b=db.get(Booking,booking_id)
    if not b:raise HTTPException(404,detail={"code":"BOOKING_NOT_FOUND"})
    require_market(principal,b.market_code)
    line=db.scalar(select(BookingLine).where(BookingLine.booking_id==b.id).limit(1))
    if not line:raise HTTPException(409,detail={"code":"BOOKING_SERVICE_MISSING"})
    offers=DispatchService.create_offers(db,booking=b,service_id=line.service_id)
    result={"items":[{"id":str(o.id),"provider_id":str(o.provider_id),"rank":o.rank,"score":float(o.score),"expires_at":o.expires_at.isoformat()} for o in offers]}
    complete(db,idem,result);db.commit();return result

@router.get("/offers")
def offers(principal:Principal=Depends(require_roles(Role.PROVIDER)),db:Session=Depends(get_db)):
    p=provider_for_principal(db,principal)
    rows=list(db.scalars(select(DispatchOffer).where(DispatchOffer.provider_id==p.id,DispatchOffer.status=="OFFERED")))
    return {"items":[{"id":str(x.id),"booking_id":str(x.booking_id),"rank":x.rank,"score":float(x.score),"expires_at":x.expires_at.isoformat()} for x in rows]}

@router.post("/offers/{offer_id}/accept")
def accept(offer_id:uuid.UUID,payload:AcceptOffer,key:str=Depends(require_idempotency_key),principal:Principal=Depends(require_roles(Role.PROVIDER)),db:Session=Depends(get_db)):
    p=provider_for_principal(db,principal)
    idem,replay=reserve(db,actor_subject=principal.subject,operation="dispatch.accept_offer",key=key,payload={"offer_id":str(offer_id),**payload.model_dump()})
    if replay is not None:return replay
    a=DispatchService.accept_offer(db,offer_id=offer_id,provider=p,expected_booking_version=payload.booking_version)
    result={"assignment_id":str(a.id),"booking_id":str(a.booking_id),"status":a.status}
    complete(db,idem,result);db.commit();return result

@router.post("/offers/{offer_id}/decline")
def decline(offer_id:uuid.UUID,key:str=Depends(require_idempotency_key),principal:Principal=Depends(require_roles(Role.PROVIDER)),db:Session=Depends(get_db)):
    p=provider_for_principal(db,principal)
    idem,replay=reserve(db,actor_subject=principal.subject,operation="dispatch.decline_offer",key=key,payload={"offer_id":str(offer_id)})
    if replay is not None:return replay
    o=db.scalar(select(DispatchOffer).where(DispatchOffer.id==offer_id,DispatchOffer.provider_id==p.id).with_for_update())
    if not o:raise HTTPException(404,detail={"code":"OFFER_NOT_FOUND"})
    o.status="DECLINED";result={"offer_id":str(o.id),"status":"DECLINED"};complete(db,idem,result);db.commit();return result

@router.get("/ops/board")
def board(principal:Principal=Depends(require_roles(Role.DISPATCHER,Role.SUPPORT)),db:Session=Depends(get_db)):
    rows=list(db.scalars(select(Booking).where(Booking.status.in_(["CONFIRMED","MATCHING","ASSIGNED","EN_ROUTE","ARRIVED","IN_SERVICE"])).order_by(Booking.scheduled_start)))
    if principal.market_codes and Role.PLATFORM_ADMIN not in principal.roles:rows=[x for x in rows if x.market_code in principal.market_codes]
    return {"items":[{"id":str(b.id),"booking_number":b.booking_number,"market_code":b.market_code,"status":b.status.value,"scheduled_start":b.scheduled_start.isoformat(),"version":b.version} for b in rows]}
