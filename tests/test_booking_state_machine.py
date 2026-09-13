import pytest

from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.domain.state_machine import ensure_transition


def test_valid_booking_transition():
    ensure_transition(BookingStatus.DRAFT, BookingStatus.QUOTED)


def test_invalid_booking_transition():
    with pytest.raises(ValueError):
        ensure_transition(BookingStatus.DRAFT, BookingStatus.SETTLED)
