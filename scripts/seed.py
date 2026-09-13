"""Idempotent deterministic demo data; credentials are supplied outside source control."""

from datetime import timedelta

from sqlalchemy import select

from larimia.config import get_settings
from larimia.marketplace.models import Address, Provider, Service, User, now
from larimia.marketplace.security import password_hash
from larimia.shared.db import SessionLocal


def seed():
    settings = get_settings()
    if settings.env == "production" or not settings.seed_password:
        raise RuntimeError("Seed requires a non-production environment and LARIMIA_SEED_PASSWORD")
    with SessionLocal.begin() as db:
        for code, name, category, amount, minutes in [
            ("MASSAGE_60", "Masaje 60 min", "massage", 450000, 60),
            ("HAIRCUT", "Corte de cabello", "haircut", 250000, 45),
            ("MAKEUP", "Maquillaje", "makeup", 400000, 60),
            ("TRAINING_60", "Entrenamiento 60 min", "personal-training", 300000, 60),
        ]:
            if not db.scalar(select(Service).where(Service.code == code)):
                db.add(
                    Service(
                        code=code,
                        name={"es-DO": name, "en-US": code},
                        category=category,
                        duration_minutes=minutes,
                        base_minor=amount,
                        required_skills=[code],
                    )
                )
        identities = [
            ("admin", ["platform_admin"]),
            ("dispatcher", ["dispatcher"]),
            ("support", ["support"]),
            ("finance", ["finance"]),
            ("customer1", ["customer"]),
            ("customer2", ["customer"]),
        ]
        identities += [(f"provider{i}", ["provider"]) for i in range(1, 6)]
        for name, roles in identities:
            email = name + "@demo.larimia.test"
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                user = User(
                    subject=email,
                    email=email,
                    roles=roles,
                    password_hash=password_hash(settings.seed_password),
                )
                db.add(user)
                db.flush()
            if "customer" in roles and not db.scalar(
                select(Address).where(Address.customer_id == user.id)
            ):
                db.add(
                    Address(
                        customer_id=user.id,
                        label="Demo Santo Domingo",
                        latitude=18.4861,
                        longitude=-69.9312,
                        market_code="DO-SDQ",
                    )
                )
            if "provider" in roles and not db.scalar(
                select(Provider).where(Provider.user_id == user.id)
            ):
                db.add(
                    Provider(
                        user_id=user.id,
                        status="SUBMITTED" if name == "provider5" else "APPROVED",
                        online=False,
                        services=["MASSAGE_60", "HAIRCUT", "MAKEUP", "TRAINING_60"],
                        skills=["MASSAGE_60", "HAIRCUT", "MAKEUP", "TRAINING_60"],
                        availability=[
                            {
                                "start": now().isoformat(),
                                "end": (now() + timedelta(days=30)).isoformat(),
                            }
                        ],
                    )
                )
    print("Seed completed; existing accounts and credentials were preserved.")


def seed_notification_templates():
    from larimia.marketplace.models import NotificationTemplate

    with SessionLocal.begin() as db:
        for event_type in [
            "CustomerRegistered",
            "ProviderApproved",
            "ProviderSuspended",
            "ProviderAssigned",
            "JobStarted",
            "JobCompleted",
            "PaymentCaptured",
            "BookingCancelled",
            "PayoutScheduled",
            "SupportTicketCreated",
        ]:
            for channel in ["email", "sms", "push"]:
                existing = db.scalar(
                    select(NotificationTemplate).where(
                        NotificationTemplate.event_type == event_type,
                        NotificationTemplate.channel == channel,
                    )
                )
                if not existing:
                    db.add(
                        NotificationTemplate(
                            event_type=event_type,
                            channel=channel,
                            subject="LARIMÍA update",
                            body="Your marketplace activity changed: $event_type.",
                        )
                    )


def seed_scenarios():

    from larimia.marketplace import schemas as s
    from larimia.marketplace import service as svc
    from larimia.marketplace.commands import command
    from larimia.marketplace.models import Earning, Payout
    from larimia.shared.events import emit

    with SessionLocal() as db:
        customer = db.scalar(select(User).where(User.email == "customer1@demo.larimia.test"))
        provider_user = db.scalar(select(User).where(User.email == "provider1@demo.larimia.test"))
        if customer is None or provider_user is None:
            raise RuntimeError("Seed identities must exist first")

        def action():
            address = db.scalar(select(Address).where(Address.customer_id == customer.id))
            provider = svc.provider_for(db, provider_user, True)
            was_online = provider.online
            identities = []
            for index in range(3):
                quote = svc.create_quote(
                    db,
                    customer,
                    s.QuoteInput(
                        service_code="MASSAGE_60",
                        address_id=address.id,
                        scheduled_start=now() + timedelta(days=1 + index),
                    ),
                )
                booking = svc.create_booking(db, customer, quote["id"])
                identities.append(str(booking["id"]))
                if index:
                    svc.authorize(
                        db,
                        customer,
                        s.AuthorizeInput(
                            booking_id=booking["id"], payment_method_token="mock_success"
                        ),
                    )
                if index == 2:
                    provider.online = True
                    db.flush()
                    dispatched = svc.dispatch(db, customer, booking["id"])
                    from larimia.marketplace.models import Offer

                    offer = db.scalar(
                        select(Offer).where(
                            Offer.booking_id == booking["id"], Offer.provider_id == provider.id
                        )
                    )
                    if offer is None:
                        raise RuntimeError(
                            "Seed provider is unavailable; seed in a fresh development database"
                        )
                    svc.accept(db, provider_user, offer.id, dispatched["version"])
                    for verb in ["en-route", "arrive", "start", "complete"]:
                        svc.job_action(db, provider_user, booking["id"], verb)
                    db.flush()
                    earning = db.scalar(select(Earning).where(Earning.booking_id == booking["id"]))
                    earning.status = "RESERVED"
                    payout = Payout(
                        provider_id=provider.id,
                        currency=earning.currency,
                        amount_minor=earning.amount_minor,
                        earning_ids=[str(earning.id)],
                        approved_by="deterministic-seed",
                    )
                    db.add(payout)
                    db.flush()
                    emit(
                        db,
                        aggregate_type="payout",
                        aggregate_id=str(payout.id),
                        event_type="PayoutScheduled",
                        payload={"user_id": str(provider_user.id), "payout_id": str(payout.id)},
                    )
            provider.online = was_online
            from larimia.marketplace.models import Promotion

            if not db.scalar(select(Promotion).where(Promotion.code == "WELCOME100")):
                db.add(
                    Promotion(
                        code="WELCOME100",
                        amount_minor=10000,
                        currency="DOP",
                        expires_at=now() + timedelta(days=30),
                    )
                )
            return {"booking_ids": identities}

        command(db, "deterministic-seed", "marketplace-scenarios", "baseline-v1", {}, action)
    print("Deterministic booking, promotion, ledger and scheduled payout scenarios are present.")


if __name__ == "__main__":
    seed()
    seed_scenarios()
    seed_notification_templates()
