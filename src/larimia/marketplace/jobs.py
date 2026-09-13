"""Job execution requirements are immutable quote values, enforced before capture."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.shared.audit import record_audit

from . import service as svc
from .models import Document, JobChecklistItem, JobTimeEntry, MarketplaceBooking, User, now


def assigned_job(db: Session, user: User, booking_id: UUID, lock: bool = False):
    booking = svc.booking_for(db, user, booking_id, lock)
    provider = svc.provider_for(db, user, lock)
    if booking.provider_id != provider.id or provider.status != "APPROVED":
        raise HTTPException(403, "Assigned approved provider required")
    return booking, provider


def checklist(db: Session, booking: MarketplaceBooking) -> dict:
    rows = db.scalars(
        select(JobChecklistItem).where(JobChecklistItem.booking_id == booking.id)
    ).all()
    values = {row.code: row for row in rows}
    requirements = booking.snapshot.get("job_policy", {})
    return {
        "booking_id": str(booking.id),
        "policy_version": requirements.get("version", 0),
        "require_time_entry": requirements.get("require_time_entry", False),
        "items": [
            {
                **item,
                "completion": svc.serialize(values[item["code"]])
                if item["code"] in values
                else None,
            }
            for item in requirements.get("items", [])
        ],
    }


def update_checklist(db: Session, user: User, booking_id: UUID, code: str, payload) -> dict:
    booking, _ = assigned_job(db, user, booking_id, True)
    if booking.status != "IN_PROGRESS":
        raise HTTPException(409, "Checklist changes require a job in progress")
    rules = booking.snapshot.get("job_policy", {}).get("items", [])
    rule = next((rule for rule in rules if rule["code"] == code), None)
    if rule is None:
        raise HTTPException(404, "Checklist requirement not found")
    if payload.evidence_id:
        evidence = db.get(Document, payload.evidence_id)
        if not evidence or evidence.booking_id != booking.id or evidence.owner_id != user.id:
            raise HTTPException(404, "Evidence not found")
        if evidence.status == "REJECTED":
            raise HTTPException(409, "Rejected evidence cannot satisfy a checklist")
    if payload.completed and rule["requires_evidence"] and not payload.evidence_id:
        raise HTTPException(422, "This item requires evidence")
    row = db.scalar(
        select(JobChecklistItem).where(
            JobChecklistItem.booking_id == booking.id, JobChecklistItem.code == code
        )
    )
    if row is None:
        row = JobChecklistItem(booking_id=booking.id, code=code, completed_by=user.id)
        db.add(row)
    row.completed, row.completed_by = payload.completed, user.id
    row.evidence_id, row.notes = payload.evidence_id, payload.notes
    db.flush()
    record_audit(
        db,
        actor=user.subject,
        action="JobChecklistUpdated",
        resource_type="job",
        resource_id=str(booking.id),
    )
    return svc.serialize(row)


def clock(db: Session, user: User, booking_id: UUID, action: str) -> dict:
    booking, provider = assigned_job(db, user, booking_id, True)
    if booking.status != "IN_PROGRESS":
        raise HTTPException(409, "Time tracking requires a job in progress")
    active = db.scalar(
        select(JobTimeEntry).where(
            JobTimeEntry.booking_id == booking.id, JobTimeEntry.ended_at.is_(None)
        )
    )
    if action == "start":
        if active:
            raise HTTPException(409, "Job already has an open time entry")
        active = JobTimeEntry(booking_id=booking.id, provider_id=provider.id)
        db.add(active)
    elif action == "stop":
        if active is None:
            raise HTTPException(409, "Job has no open time entry")
        active.ended_at = now()
    else:
        raise HTTPException(404, "Unknown time action")
    db.flush()
    record_audit(
        db,
        actor=user.subject,
        action="JobTime" + action.title(),
        resource_type="job",
        resource_id=str(booking.id),
    )
    return svc.serialize(active)


def validate_completion(db: Session, booking: MarketplaceBooking) -> None:
    policy = booking.snapshot.get("job_policy", {})
    items = {
        row.code: row
        for row in db.scalars(
            select(JobChecklistItem).where(JobChecklistItem.booking_id == booking.id)
        )
    }
    for rule in policy.get("items", []):
        row = items.get(rule["code"])
        if row is None or not row.completed:
            raise HTTPException(409, "Required job checklist is incomplete")
        if rule["requires_evidence"]:
            evidence = db.get(Document, row.evidence_id) if row.evidence_id else None
            if not evidence or evidence.booking_id != booking.id or evidence.status != "CLEARED":
                raise HTTPException(409, "Required evidence must be reviewed and cleared")
    entries = db.scalars(select(JobTimeEntry).where(JobTimeEntry.booking_id == booking.id)).all()
    if any(entry.ended_at is None for entry in entries):
        raise HTTPException(409, "Stop the open time entry before completing the job")
    if policy.get("require_time_entry") and not any(
        entry.ended_at and entry.ended_at > entry.started_at for entry in entries
    ):
        raise HTTPException(409, "A completed time entry is required")
