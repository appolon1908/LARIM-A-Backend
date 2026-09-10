import pytest

from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.domain.state_machine import can_transition, ensure_transition
from larimia.shared.errors import ConflictError


def test_valid_booking_transition():
    ensure_transition(BookingStatus.DRAFT, BookingStatus.QUOTED)
    assert can_transition(BookingStatus.QUOTED, BookingStatus.CONFIRMED)


def test_invalid_booking_transition():
    with pytest.raises(ConflictError) as exc_info:
        ensure_transition(BookingStatus.DRAFT, BookingStatus.SETTLED)
    assert exc_info.value.code == "INVALID_BOOKING_TRANSITION"


def test_in_service_booking_cannot_be_cancelled():
    assert not can_transition(
        BookingStatus.IN_SERVICE,
        BookingStatus.CANCELLED,
    )
