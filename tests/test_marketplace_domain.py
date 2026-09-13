import pytest

from larimia.marketplace.domain import balanced, price, score, transition


def test_full_state_path():
    states = [
        "DRAFT",
        "QUOTED",
        "PAYMENT_AUTHORIZED",
        "SEARCHING",
        "OFFERED",
        "ASSIGNED",
        "PROVIDER_EN_ROUTE",
        "ARRIVED",
        "IN_PROGRESS",
        "COMPLETED",
        "PAYMENT_CAPTURED",
        "SETTLED",
    ]
    for current, target in zip(states, states[1:], strict=False):
        transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        ("ASSIGNED", "COMPLETED"),
        ("CANCELLED", "SEARCHING"),
        ("QUOTED", "SETTLED"),
        ("REFUNDED", "PAYMENT_CAPTURED"),
    ],
)
def test_illegal_transitions(current, target):
    with pytest.raises(ValueError):
        transition(current, target)


def test_pricing_uses_exact_minor_units():
    value = price(10001, 500, 1800, 2000)
    assert value["tax_minor"] == 1890
    assert value["platform_fee_minor"] == 2000
    assert value["provider_earning_minor"] == 8501
    assert value["total_minor"] == 12391


@pytest.mark.parametrize(
    "entries",
    [
        [("a", "DEBIT", 1)],
        [("a", "DEBIT", 3), ("b", "CREDIT", 2)],
        [("a", "DEBIT", -1), ("b", "CREDIT", -1)],
    ],
)
def test_ledger_rejects_invalid_entries(entries):
    with pytest.raises(ValueError):
        balanced(entries)


def test_balanced_entry():
    balanced([("processor", "DEBIT", 100), ("provider", "CREDIT", 80), ("fee", "CREDIT", 20)])


def test_configurable_dispatch_fairness():
    weights = dict(distance=0.4, rating=0.2, completion=0.3, workload=0.1)
    assert score(1, 5, 1, 0, weights) > score(1, 5, 1, 2, weights)
