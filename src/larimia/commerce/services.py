import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from larimia.commerce.models import MembershipCredit, MembershipEvent, MembershipPlan
from larimia.marketplace.models import Membership
from larimia.shared.events import emit


LIVE_MEMBERSHIP_STATUSES = {"PENDING_PAYMENT", "ACTIVE", "PAST_DUE"}


def credit_balance(db: Session, customer_id: uuid.UUID) -> int:
    granted = db.scalar(
        select(func.coalesce(func.sum(MembershipCredit.granted_quantity), 0)).where(
            MembershipCredit.customer_id == customer_id,
            MembershipCredit.expires_at.is_(None) | (MembershipCredit.expires_at > datetime.now(UTC)),
        )
    ) or 0
    consumed = db.scalar(
        select(func.coalesce(func.sum(MembershipCredit.consumed_quantity), 0)).where(
            MembershipCredit.customer_id == customer_id,
            MembershipCredit.expires_at.is_(None) | (MembershipCredit.expires_at > datetime.now(UTC)),
        )
    ) or 0
    return int(granted) - int(consumed)


def apply_subscription_renewal(
    db: Session,
    *,
    provider_code: str,
    external_event_id: str,
    customer_id: uuid.UUID,
    plan_code: str,
    external_subscription_id: str,
    period_start: datetime,
    period_end: datetime,
    payload: dict,
) -> Membership:
    """Apply an authenticated provider renewal exactly once."""
    existing_event = db.scalar(
        select(MembershipEvent).where(
            MembershipEvent.provider_code == provider_code,
            MembershipEvent.external_event_id == external_event_id,
        )
    )
    if existing_event is not None:
        if existing_event.membership_id is None:
            raise RuntimeError("Processed membership event lost membership reference")
        membership = db.get(Membership, existing_event.membership_id)
        if membership is None:
            raise RuntimeError("Processed membership event references missing membership")
        return membership

    plan = db.get(MembershipPlan, plan_code)
    if plan is None or not plan.active:
        raise ValueError("Membership plan is not active")
    if period_start.tzinfo is None or period_end.tzinfo is None or period_end <= period_start:
        raise ValueError("Membership period must be timezone-aware and increasing")

    membership = db.scalar(
        select(Membership)
        .where(Membership.customer_id == customer_id)
        .where(Membership.status.in_(sorted(LIVE_MEMBERSHIP_STATUSES)))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if membership is None:
        membership = Membership(
            customer_id=customer_id,
            plan_code=plan.code,
            status="ACTIVE",
            external_subscription_id=external_subscription_id,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=False,
            version=1,
            started_at=period_start,
            created_at=now,
            updated_at=now,
        )
        db.add(membership)
        db.flush()
    else:
        membership.plan_code = plan.code
        membership.status = "ACTIVE"
        membership.external_subscription_id = external_subscription_id
        membership.current_period_start = period_start
        membership.current_period_end = period_end
        membership.cancel_at_period_end = False
        membership.version += 1
        membership.updated_at = now

    event = MembershipEvent(
        membership_id=membership.id,
        provider_code=provider_code,
        external_event_id=external_event_id,
        event_type="subscription.renewed",
        payload=payload,
        processed_at=now,
    )
    db.add(event)

    if plan.credits_per_period > 0:
        db.add(
            MembershipCredit(
                customer_id=customer_id,
                membership_id=membership.id,
                source_event_id=f"{provider_code}:{external_event_id}",
                credit_type="SERVICE",
                granted_quantity=plan.credits_per_period,
                consumed_quantity=0,
                expires_at=period_end,
                created_at=now,
            )
        )

    emit(
        db,
        aggregate_type="membership",
        aggregate_id=str(membership.id),
        event_type="membership.renewed.v1",
        payload={
            "membership_id": str(membership.id),
            "customer_id": str(customer_id),
            "plan_code": plan.code,
            "period_end": period_end.isoformat(),
        },
    )
    db.flush()
    return membership
