import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from larimia.config import get_settings
from larimia.api.router import api_router
from larimia.shared.errors import DomainError

settings = get_settings()

app = FastAPI(
    title="LARIMÍA API",
    version="0.2.0",
    default_response_class=ORJSONResponse,
    description="Production-oriented marketplace API for Customer, Pro and Operations.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "X-Request-Id", "X-Demo-Subject", "X-Demo-Roles"],
)

@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return ORJSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message}, "request_id": request.headers.get("X-Request-Id")},
    )

app.include_router(api_router, prefix="/v1")

