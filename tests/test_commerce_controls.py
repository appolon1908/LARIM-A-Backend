import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from larimia.commerce.models import MembershipCredit, MembershipEvent, MembershipPlan
from larimia.commerce.services import apply_subscription_renewal, credit_balance
from larimia.marketplace.models import Customer, Membership
from larimia.shared.db import SessionLocal


def test_membership_renewal_is_idempotent_and_grants_credit_once():
    now = datetime.now(UTC)
    with SessionLocal() as db:
        customer = Customer(
            identity_issuer="test",
            identity_subject=f"commerce-{uuid.uuid4()}",
            market_code="DO-SDQ",
            preferred_language="es-DO",
            status="ACTIVE",
            created_at=now,
            version=1,
        )
        db.add(customer)
        db.flush()
        plan = db.get(MembershipPlan, "LARIMIA_PLUS")
        assert plan is not None

        event_id = f"evt-{uuid.uuid4()}"
        first = apply_subscription_renewal(
            db,
            provider_code="test-payments",
            external_event_id=event_id,
            customer_id=customer.id,
            plan_code=plan.code,
            external_subscription_id=f"sub-{uuid.uuid4()}",
            period_start=now,
            period_end=now + timedelta(days=30),
            payload={"test": True},
        )
        second = apply_subscription_renewal(
            db,
            provider_code="test-payments",
            external_event_id=event_id,
            customer_id=customer.id,
            plan_code=plan.code,
            external_subscription_id=first.external_subscription_id,
            period_start=now,
            period_end=now + timedelta(days=30),
            payload={"test": True},
        )
        db.flush()

        assert first.id == second.id
        assert first.status == "ACTIVE"
        assert credit_balance(db, customer.id) == plan.credits_per_period
        assert db.scalar(
            select(func.count(MembershipEvent.id)).where(
                MembershipEvent.provider_code == "test-payments",
                MembershipEvent.external_event_id == event_id,
            )
        ) == 1
        assert db.scalar(
            select(func.count(MembershipCredit.id)).where(
                MembershipCredit.membership_id == first.id
            )
        ) == 1
        assert db.scalar(
            select(func.count(Membership.id)).where(Membership.customer_id == customer.id)
        ) == 1
        db.rollback()
