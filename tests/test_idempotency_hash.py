from larimia.shared.idempotency_service import request_hash


def test_hash_order_stable():
    assert request_hash({"a": 1, "b": 2}) == request_hash({"b": 2, "a": 1})


def test_hash_detects_change():
    assert request_hash({"a": 1}) != request_hash({"a": 2})
