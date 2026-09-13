from fastapi.testclient import TestClient

from larimia.main import app


def test_live_health():
    client = TestClient(app)
    response = client.get("/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
