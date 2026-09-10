from collections.abc import Callable
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
    return set(get_settings().capability_set)


def capability_enabled(capability: Capability) -> bool:
    return capability.value in enabled_capabilities()


def ensure_capability(capability: Capability) -> None:
    if capability_enabled(capability):
        return
    raise HTTPException(
        status_code=503,
        detail={
            "code": "CAPABILITY_DISABLED",
            "capability": capability.value,
        },
    )


def require_capability(capability: Capability) -> Callable[[], None]:
    def dependency() -> None:
        ensure_capability(capability)

    return dependency
