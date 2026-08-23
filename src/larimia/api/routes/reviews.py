import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()

class ReviewCreate(BaseModel):
    booking_id: str
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    safety_flag: bool = False

@router.post("", status_code=201)
def create_review(payload: ReviewCreate, _: str = Depends(require_idempotency_key)):
    return {"review_id": str(uuid.uuid4()), "status": "PUBLISHED" if not payload.safety_flag else "HELD_FOR_REVIEW", **payload.model_dump()}
