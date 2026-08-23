from larimia.shared.idempotency_service import request_hash

def test_request_hash_is_order_independent():
    assert request_hash({"a": 1, "b": 2}) == request_hash({"b": 2, "a": 1})

def test_request_hash_changes_with_payload():
    assert request_hash({"a": 1}) != request_hash({"a": 2})
