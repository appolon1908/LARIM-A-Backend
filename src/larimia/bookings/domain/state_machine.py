from larimia.bookings.domain.enums import BookingStatus
from larimia.shared.errors import ConflictError


ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.DRAFT: {BookingStatus.QUOTED, BookingStatus.CANCELLED},
    BookingStatus.QUOTED: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.MATCHING, BookingStatus.CANCELLED},
    BookingStatus.MATCHING: {BookingStatus.ASSIGNED, BookingStatus.CANCELLED},
    BookingStatus.ASSIGNED: {
        BookingStatus.EN_ROUTE,
        BookingStatus.MATCHING,
        BookingStatus.CANCELLED,
    },
    BookingStatus.EN_ROUTE: {
        BookingStatus.ARRIVED,
        BookingStatus.MATCHING,
        BookingStatus.CANCELLED,
    },
    BookingStatus.ARRIVED: {
        BookingStatus.IN_SERVICE,
        BookingStatus.CANCELLED,
    },
    BookingStatus.IN_SERVICE: {BookingStatus.COMPLETED},
    BookingStatus.COMPLETED: {
        BookingStatus.SETTLING,
        BookingStatus.DISPUTED,
    },
    BookingStatus.SETTLING: {
        BookingStatus.SETTLED,
        BookingStatus.DISPUTED,
    },
    BookingStatus.DISPUTED: {BookingStatus.SETTLED},
    BookingStatus.SETTLED: set(),
    BookingStatus.CANCELLED: set(),
}


def can_transition(current: BookingStatus, target: BookingStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: BookingStatus, target: BookingStatus) -> None:
    if can_transition(current, target):
        return
    raise ConflictError(
        "INVALID_BOOKING_TRANSITION",
        f"Booking cannot transition from {current.value} to {target.value}",
    )
