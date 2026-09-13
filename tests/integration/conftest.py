import pytest
from redis import Redis

from larimia.config import get_settings


@pytest.fixture(autouse=True)
def isolated_environment():
    settings = get_settings()
    if settings.env != "development" or settings.auth_mode != "local":
        pytest.fail(
            "Marketplace integration tests require the isolated local development configuration"
        )
    cache = Redis.from_url(settings.redis_url)
    # Tests use Starlette's synthetic source; never clear real clients' buckets.
    import hashlib

    identity = hashlib.sha256(b"testclient").hexdigest()
    cache.delete("larimia:ratelimit:auth:" + identity, "larimia:ratelimit:api:" + identity)
    yield
    cache.close()
