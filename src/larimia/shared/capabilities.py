from enum import StrEnum

from fastapi import HTTPException

from larimia.config import get_settings


class Capability(StrEnum):
    REQUEST_INTAKE = "request_intake"
    PROVIDER_SELF_SERVICE = "provider_self_service"
    MATCHING = "matching"
    QUOTES = "quotes"
    MESSAGING = "messaging"
    REVIEWS = "reviews"
    INSTANT_BOOKING = "instant_booking"
    AUTOMATIC_ASSIGNMENT = "automatic_assignment"
    PAYMENTS = "payments"
    PAYOUTS = "payouts"
    MEMBERSHIPS = "memberships"
    PARTNERS = "partners"


def enabled_capabilities() -> set[str]:
    settings = get_settings()
    return {x.strip() for x in settings.enabled_capabilities.split(",") if x.strip()}


def require_capability(capability: Capability):
    def dependency() -> None:
        if capability.value not in enabled_capabilities():
            raise HTTPException(
                status_code=503,
                detail={"code": "CAPABILITY_DISABLED", "capability": capability.value},
            )

    return dependency
