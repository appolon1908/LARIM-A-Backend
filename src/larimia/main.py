import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from larimia.api.router import api_router
from larimia.config import get_settings
from larimia.shared.errors import DomainError


settings = get_settings()

app = FastAPI(
    title="LARIMÍA API",
    version="0.2.1",
    default_response_class=ORJSONResponse,
    description="Production-oriented marketplace API for Customer, Pro and Operations.",
)

allowed_headers = [
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "If-Match",
    "X-Request-Id",
]
if settings.env.lower() != "production":
    allowed_headers.extend(["X-Demo-Subject", "X-Demo-Roles"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=allowed_headers,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return ORJSONResponse(
        status_code=exc.http_status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
            "request_id": getattr(request.state, "request_id", None),
        },
    )


app.include_router(api_router, prefix="/v1")
