import uuid
from datetime import datetime,timezone
from fastapi import APIRouter,Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from larimia.marketplace.models import CustomerAddress,DeviceRegistration
from larimia.shared.auth import Principal,get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.db import get_db
router=APIRouter()

class AddressCreate(BaseModel):
    label:str;place_type:str;address_line_1:str;city:str;country_code:str;latitude:float;longitude:float;access_notes:str|None=None
class DeviceCreate(BaseModel):
    platform:str;token:str

@router.get("/me")
def me(principal:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    c=customer_for_principal(db,principal)
    return {"id":str(c.id),"market_code":c.market_code,"preferred_language":c.preferred_language,"status":c.status}

@router.get("/me/addresses")
def addresses(principal:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    c=customer_for_principal(db,principal)
    rows=list(db.scalars(select(CustomerAddress).where(CustomerAddress.customer_id==c.id,CustomerAddress.active.is_(True))))
    return {"items":[{"id":str(x.id),"label":x.label,"place_type":x.place_type,"city":x.city,"country_code":x.country_code,"latitude":float(x.latitude),"longitude":float(x.longitude)} for x in rows]}

@router.post("/me/addresses",status_code=201)
def add_address(payload:AddressCreate,principal:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    c=customer_for_principal(db,principal);row=CustomerAddress(customer_id=c.id,active=True,**payload.model_dump());db.add(row);db.commit();db.refresh(row);return {"id":str(row.id)}

@router.post("/me/devices",status_code=201)
def device(payload:DeviceCreate,principal:Principal=Depends(get_principal),db:Session=Depends(get_db)):
    row=db.scalar(select(DeviceRegistration).where(DeviceRegistration.token==payload.token))
    if not row:row=DeviceRegistration(identity_subject=principal.subject,platform=payload.platform,token=payload.token,active=True,updated_at=datetime.now(timezone.utc));db.add(row)
    else:row.identity_subject=principal.subject;row.platform=payload.platform;row.active=True;row.updated_at=datetime.now(timezone.utc)
    db.commit();return {"status":"registered"}
