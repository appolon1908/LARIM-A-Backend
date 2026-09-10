import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.commerce.models import MembershipPlan
from larimia.commerce.services import LIVE_MEMBERSHIP_STATUSES, credit_balance
from larimia.marketplace.models import Membership
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter(dependencies=[Depends(require_capability(Capability.MEMBERSHIPS))])


class Subscribe(BaseModel):
    plan_code: str = Field(min_length=1, max_length=80)
    billing_setup_reference: str = Field(min_length=8, max_length=255)


@router.get("/plans")
def plans(db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(MembershipPlan)
            .where(MembershipPlan.active.is_(True))
            .order_by(MembershipPlan.price_minor, MembershipPlan.code)
        )
    )
    return {
        "items": [
            {
                "code": row.code,
                "name": {"es-DO": row.name_es, "en-US": row.name_en},
                "currency": row.currency,
                "price_minor": row.price_minor,
                "credits_per_period": row.credits_per_period,
                "billing_interval": row.billing_interval,
            }
            for row in rows
        ]
    }


@router.get("/subscriptions/me")
def current_subscription(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    membership = db.scalar(
        select(Membership)
        .where(Membership.customer_id == customer.id)
        .where(Membership.status.in_(sorted(LIVE_MEMBERSHIP_STATUSES)))
        .order_by(Membership.started_at.desc())
    )
    return {
        "membership": None
        if membership is None
        else {
            "id": str(membership.id),
            "plan_code": membership.plan_code,
            "status": membership.status,
            "current_period_start": membership.current_period_start.isoformat()
            if membership.current_period_start
            else None,
            "current_period_end": membership.current_period_end.isoformat()
            if membership.current_period_end
            else None,
            "cancel_at_period_end": membership.cancel_at_period_end,
            "version": membership.version,
        },
        "credit_balance": credit_balance(db, customer.id),
    }


@router.post("/subscriptions", status_code=202)
def subscribe(
    payload: Subscribe,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    plan = db.get(MembershipPlan, payload.plan_code)
    if plan is None or not plan.active:
        raise HTTPException(422, detail={"code": "MEMBERSHIP_PLAN_INVALID"})

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="membership.subscribe",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay

    membership = db.scalar(
        select(Membership)
        .where(Membership.customer_id == customer.id)
        .where(Membership.status.in_(sorted(LIVE_MEMBERSHIP_STATUSES)))
        .with_for_update()
    )
    if membership is not None:
        raise HTTPException(409, detail={"code": "MEMBERSHIP_ALREADY_LIVE"})

    now = datetime.now(UTC)
    membership = Membership(
        customer_id=customer.id,
        plan_code=plan.code,
        status="PENDING_PAYMENT",
        external_subscription_id=None,
        current_period_start=None,
        current_period_end=None,
        cancel_at_period_end=False,
        version=1,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(membership)
    db.flush()
    emit(
        db,
        aggregate_type="membership",
        aggregate_id=str(membership.id),
        event_type="membership.billing_setup_requested.v1",
        payload={
            "membership_id": str(membership.id),
            "customer_id": str(customer.id),
            "plan_code": plan.code,
            "billing_setup_reference": payload.billing_setup_reference,
        },
    )
    result = {
        "id": str(membership.id),
        "plan_code": plan.code,
        "status": membership.status,
        "version": membership.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/subscriptions/{membership_id}/cancel")
def cancel_subscription(
    membership_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    membership = db.scalar(
        select(Membership)
        .where(Membership.id == membership_id, Membership.customer_id == customer.id)
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(404, detail={"code": "MEMBERSHIP_NOT_FOUND"})
    if membership.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    if membership.status not in LIVE_MEMBERSHIP_STATUSES:
        raise HTTPException(409, detail={"code": "MEMBERSHIP_NOT_CANCELLABLE"})

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="membership.cancel",
        key=key,
        payload={"membership_id": str(membership_id), "version": if_match},
    )
    if replay is not None:
        return replay

    membership.cancel_at_period_end = True
    membership.version += 1
    membership.updated_at = datetime.now(UTC)
    emit(
        db,
        aggregate_type="membership",
        aggregate_id=str(membership.id),
        event_type="membership.cancellation_requested.v1",
        payload={"membership_id": str(membership.id), "version": membership.version},
    )
    result = {
        "id": str(membership.id),
        "status": membership.status,
        "cancel_at_period_end": True,
        "version": membership.version,
    }
    complete(db, idem, result)
    db.commit()
    return result
