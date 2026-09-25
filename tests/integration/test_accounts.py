from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from test_marketplace_e2e import login

from larimia.config import get_settings
from larimia.main import app

client = TestClient(app)


def account_login(name, device_id=None):
    body = {"email": name + "@demo.larimia.test", "password": get_settings().seed_password}
    if device_id:
        body["device_id"] = device_id
    return client.post("/api/v1/auth/login", json=body)


def register_device(owner):
    key = str(uuid4())
    headers = {**owner, "Idempotency-Key": key}
    body = {"label": "Test phone", "platform": "ios"}
    first = client.post("/api/v1/me/devices", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert client.post("/api/v1/me/devices", json=body, headers=headers).json() == first.json()
    assert "user_id" not in first.json()
    return first.json()["id"]


def test_profile_preferences_are_owned_and_validated():
    owner, other = login("customer1"), login("customer2")
    baseline = client.get("/api/v1/me/profile", headers=other).json()
    payload = {
        "display_name": "Local profile",
        "locale": "es-DO",
        "timezone": "America/Santo_Domingo",
    }
    headers = {**owner, "Idempotency-Key": str(uuid4())}
    assert client.put("/api/v1/me/profile", json=payload, headers=headers).status_code == 200
    assert client.get("/api/v1/me/profile", headers=owner).json() == payload
    assert client.get("/api/v1/me/profile", headers=other).json() == baseline
    assert (
        client.put(
            "/api/v1/me/profile", json={**payload, "roles": ["administrator"]}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/me/profile", json={**payload, "timezone": "../invalid"}, headers=headers
        ).status_code
        == 422
    )
    preferences = {
        "preferred_service_codes": ["MASSAGE_60"],
        "accessibility_notes": "Step-free entrance",
        "contact_preference": "in_app",
    }
    response = client.put(
        "/api/v1/me/preferences",
        json=preferences,
        headers={**owner, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200 and response.json() == preferences
    invalid = {**preferences, "preferred_service_codes": ["same", "same"]}
    assert (
        client.put(
            "/api/v1/me/preferences",
            json=invalid,
            headers={**owner, "Idempotency-Key": str(uuid4())},
        ).status_code
        == 422
    )


def test_device_ownership_and_revocation_invalidate_access_and_refresh():
    owner, other = login("customer1"), login("customer2")
    device_id = register_device(owner)
    assert account_login("customer2", device_id).status_code == 401
    bound = account_login("customer1", device_id).json()
    access = {"Authorization": "Bearer " + bound["access_token"]}
    assert client.get("/api/v1/me", headers=access).status_code == 200
    path = "/api/v1/me/devices/" + device_id
    assert (
        client.delete(path, headers={**other, "Idempotency-Key": str(uuid4())}).status_code == 404
    )
    assert (
        client.delete(path, headers={**owner, "Idempotency-Key": str(uuid4())}).status_code == 200
    )
    assert client.get("/api/v1/me", headers=access).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": bound["refresh_token"]}
        ).status_code
        == 401
    )
    assert account_login("customer1", device_id).status_code == 401
    import pytest
    from fastapi import HTTPException

    from larimia.marketplace.realtime import identify

    with pytest.raises(HTTPException) as failure:
        identify(bound["access_token"])
    assert failure.value.status_code == 401


def test_refresh_rotation_and_logout_revoke_access_tokens():
    initial = account_login("customer1").json()
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": initial["refresh_token"]})
    assert rotated.status_code == 200
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer " + initial["access_token"]}
        ).status_code
        == 401
    )
    tokens = rotated.json()
    header = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.get("/api/v1/me", headers=header).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/logout", headers=header, json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 204
    )
    assert client.get("/api/v1/me", headers=header).status_code == 401


def test_refresh_cannot_escape_concurrent_device_revocation():
    owner = login("customer1")
    device_id = register_device(owner)
    tokens = account_login("customer1", device_id).json()

    def refresh():
        return client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    def revoke():
        return client.delete(
            "/api/v1/me/devices/" + device_id, headers={**owner, "Idempotency-Key": str(uuid4())}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(refresh), executor.submit(revoke)
        refreshed, revoked = a.result(), b.result()
    assert revoked.status_code == 200
    assert refreshed.status_code in {200, 401}
    if refreshed.status_code == 200:
        assert (
            client.get(
                "/api/v1/me",
                headers={"Authorization": "Bearer " + refreshed.json()["access_token"]},
            ).status_code
            == 401
        )


def test_open_websocket_closes_when_its_device_is_revoked():
    import pytest
    from starlette.websockets import WebSocketDisconnect

    owner = login("customer1")
    device_id = register_device(owner)
    tokens = account_login("customer1", device_id).json()
    with client.websocket_connect("/api/v1/realtime") as socket:
        socket.send_json({"access_token": tokens["access_token"]})
        assert socket.receive_json()["type"] == "connected"
        response = client.delete(
            "/api/v1/me/devices/" + device_id, headers={**owner, "Idempotency-Key": str(uuid4())}
        )
        assert response.status_code == 200
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(3):
                socket.receive_json()
        assert closed.value.code == 1008
