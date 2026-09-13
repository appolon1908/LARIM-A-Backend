"""Bounded request bodies, connection-source rate limiting and redacted request logs."""

import hashlib
import json
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.responses import JSONResponse

from larimia.config import get_settings


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                **{
                    key: getattr(record, key)
                    for key in ("request_id", "trace_id", "route", "status", "duration_ms")
                    if hasattr(record, key)
                },
            }
        )


class RequestLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Bound actual received chunks, including requests without Content-Length.
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 1048576:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "Maximum request body is 1 MiB",
                            "details": {},
                            "trace_id": "",
                        }
                    },
                    413,
                )
                return await response(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        if not scope["path"].endswith(("/health/live", "/health/ready")):
            settings = get_settings()
            client = (scope.get("client") or ("unknown", 0))[0]
            bucket = hashlib.sha256(client.encode()).hexdigest()
            auth_route = "/auth/" in scope["path"]
            key = "larimia:ratelimit:" + ("auth:" if auth_route else "api:") + bucket
            cache = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
            try:
                count = await cache.eval(
                    "local n=redis.call('INCR',KEYS[1]); if n==1 then "
                    "redis.call('EXPIRE',KEYS[1],60) end; return n",
                    1,
                    key,
                )
                if count > (30 if auth_route else settings.rate_limit_per_minute):
                    response = JSONResponse(
                        {
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": "Request limit reached",
                                "details": {},
                                "trace_id": "",
                            }
                        },
                        429,
                        headers={"Retry-After": "60"},
                    )
                    return await response(scope, receive, send)
            except RedisError:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "RATE_LIMIT_UNAVAILABLE",
                            "message": "Authentication protection temporarily unavailable",
                            "details": {},
                            "trace_id": "",
                        }
                    },
                    503,
                )
                return await response(scope, receive, send)
            finally:
                await cache.aclose()
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
