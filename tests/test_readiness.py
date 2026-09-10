from unittest.mock import Mock

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from larimia.api.routes import health
from larimia.main import app
from larimia.shared.db import get_db


@pytest.fixture
def dependencies(monkeypatch):
    database = Mock()
    cache = Mock()
    monkeypatch.setattr(health.redis.Redis, "from_url", Mock(return_value=cache))
    app.dependency_overrides[get_db] = lambda: database
    try:
        yield database, cache
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ready_preserves_success_response_and_closes_cache(dependencies):
    _, cache = dependencies
    response = TestClient(app).get("/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    cache.close.assert_called_once()


def test_database_outage_returns_service_unavailable(dependencies):
    database, cache = dependencies
    database.execute.side_effect = OperationalError("SELECT 1", {}, Exception("private detail"))
    response = TestClient(app).get("/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    cache.ping.assert_not_called()


def test_cache_outage_returns_service_unavailable_and_closes_cache(dependencies):
    _, cache = dependencies
    cache.ping.side_effect = redis.ConnectionError("private detail")
    response = TestClient(app).get("/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    cache.close.assert_called_once()
