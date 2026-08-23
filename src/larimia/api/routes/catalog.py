from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from larimia.shared.auth import Principal, Role, require_roles

router = APIRouter()

CATALOG = [
    {"code": "MASSAGE_60", "category": "massage", "name": {"es-DO": "Masaje 60 min", "en-US": "60 min Massage"}, "duration_minutes": 60},
    {"code": "HAIRCUT", "category": "haircut", "name": {"es-DO": "Corte de cabello", "en-US": "Haircut"}, "duration_minutes": 45},
    {"code": "MAKEUP", "category": "makeup", "name": {"es-DO": "Maquillaje", "en-US": "Makeup"}, "duration_minutes": 60},
    {"code": "TRAINING_60", "category": "personal-training", "name": {"es-DO": "Entrenamiento 60 min", "en-US": "60 min Training"}, "duration_minutes": 60},
]

class ServiceUpsert(BaseModel):
    code: str = Field(min_length=3, max_length=80)
    category: str
    name: dict[str, str]
    duration_minutes: int = Field(gt=0, le=480)

@router.get("")
def list_catalog(market: str = "DO-SDQ"):
    return {"market": market, "services": CATALOG}

@router.post("", status_code=201)
def create_service(payload: ServiceUpsert, _: Principal = Depends(require_roles(Role.CATALOG_MANAGER))):
    return {"status": "created", "service": payload.model_dump()}
