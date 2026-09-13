from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.shared.audit import record_audit
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key

from . import jobs
from . import service as svc
from .models import Document, JobTimeEntry, Service, ServiceJobPolicy, User
from .routes import run
from .security import require

router = APIRouter(tags=["job-execution"])


class ChecklistRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    label: str = Field(min_length=1, max_length=200)
    requires_evidence: bool = False


class JobPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ChecklistRequirement] = Field(default_factory=list, max_length=50)
    require_time_entry: bool = False

    @model_validator(mode="after")
    def unique_codes(self):
        if len({item.code for item in self.items}) != len(self.items):
            raise ValueError("Checklist codes must be unique")
        return self


class ChecklistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: bool
    evidence_id: UUID | None = None
    notes: str = Field(default="", max_length=2000)


class EvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["CLEARED", "REJECTED"]
    reason: str = Field(min_length=5, max_length=1000)


@router.put("/admin/catalog/{service_id}/job-policy")
def policy(
    service_id: UUID,
    payload: JobPolicyInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("catalog.manage")),
    db: Session = Depends(get_db),
):
    def action():
        svc.get(db, Service, service_id, True)
        row = db.scalar(select(ServiceJobPolicy).where(ServiceJobPolicy.service_id == service_id))
        if row is None:
            row = ServiceJobPolicy(service_id=service_id, version=1)
            db.add(row)
        else:
            row.version += 1
        row.requirements = payload.model_dump()
        db.flush()
        record_audit(
            db,
            actor=user.subject,
            action="JobPolicyChanged",
            resource_type="service",
            resource_id=str(service_id),
        )
        return svc.serialize(row)

    return run(db, user, "job.policy:" + str(service_id), key, payload.model_dump(), action)


@router.get("/provider/jobs/{booking_id}/checklist")
def checklist(
    booking_id: UUID,
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    booking, _ = jobs.assigned_job(db, user, booking_id)
    return jobs.checklist(db, booking)


@router.put("/provider/jobs/{booking_id}/checklist/{code}")
def update_checklist(
    booking_id: UUID,
    code: str,
    payload: ChecklistInput,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        f"job.checklist:{booking_id}:{code}",
        key,
        payload.model_dump(),
        lambda: jobs.update_checklist(db, user, booking_id, code, payload),
    )


@router.post("/provider/jobs/{booking_id}/time/{action}")
def time_action(
    booking_id: UUID,
    action: Literal["start", "stop"],
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    return run(
        db,
        user,
        f"job.time:{booking_id}:{action}",
        key,
        {},
        lambda: jobs.clock(db, user, booking_id, action),
    )


@router.get("/provider/jobs/{booking_id}/time")
def time_entries(
    booking_id: UUID,
    user: User = Depends(require("provider.self")),
    db: Session = Depends(get_db),
):
    jobs.assigned_job(db, user, booking_id)
    return {
        "items": [
            svc.serialize(row)
            for row in db.scalars(
                select(JobTimeEntry)
                .where(JobTimeEntry.booking_id == booking_id)
                .order_by(JobTimeEntry.started_at.desc())
                .limit(100)
            )
        ]
    }


@router.post("/admin/jobs/evidence/{document_id}/review")
def review_evidence(
    document_id: UUID,
    payload: EvidenceReview,
    key: str = Depends(require_idempotency_key),
    user: User = Depends(require("job.evidence.review")),
    db: Session = Depends(get_db),
):
    def action():
        initial = svc.get(db, Document, document_id)
        if not initial.booking_id:
            raise HTTPException(409, "Document is not job evidence")
        # Same booking-first lock order as completion; a review cannot race a capture.
        from .models import MarketplaceBooking

        booking = svc.get(db, MarketplaceBooking, initial.booking_id, True)
        row = svc.get(db, Document, document_id, True)
        if row.owner_id == user.id:
            raise HTTPException(403, "An independent reviewer is required")
        if booking.status not in {"ASSIGNED", "PROVIDER_EN_ROUTE", "ARRIVED", "IN_PROGRESS"}:
            raise HTTPException(409, "Evidence review is closed for this job state")
        row.status = payload.decision
        record_audit(
            db,
            actor=user.subject,
            action="JobEvidence" + payload.decision.title(),
            resource_type="document",
            resource_id=str(row.id),
            metadata={"reason": payload.reason},
        )
        return {"document_id": str(row.id), "status": row.status}

    return run(
        db, user, "job.evidence.review:" + str(document_id), key, payload.model_dump(), action
    )
