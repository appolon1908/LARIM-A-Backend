import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from redis import Redis
from sqlalchemy import text

from larimia.config import get_settings
from larimia.marketplace.account_api import router as account_router
from larimia.marketplace.http_security import JsonFormatter, RequestLimits
from larimia.marketplace.job_api import router as job_router
from larimia.marketplace.notification_api import router as notification_router
from larimia.marketplace.operations import router as operations_router
from larimia.marketplace.realtime import router as realtime_router
from larimia.marketplace.routes import router
from larimia.marketplace.telemetry import setup
from larimia.shared.db import SessionLocal, engine
from larimia.shared.errors import DomainError

settings = get_settings()
setup()
app = FastAPI(
    title="LARIMÍA API",
    version="0.3.0",
    description="Persisted marketplace API; local payment gateway is simulated.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    try:
        request.state.request_id = str(uuid.UUID(request.headers.get("X-Request-Id", "")))
    except ValueError:
        request.state.request_id = str(uuid.uuid4())
    from opentelemetry import trace

    request.state.trace_id = format(trace.get_current_span().get_span_context().trace_id, "032x")
    start = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    logging.getLogger("larimia.requests").info(
        "request",
        extra={
            "request_id": request.state.request_id,
            "trace_id": request.state.trace_id,
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - start) * 1000),
            "route": getattr(request.scope.get("route"), "path", "unmatched"),
        },
    )
    return response


def error_response(request, status, code, message):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "trace_id": getattr(request.state, "trace_id", ""),
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    return error_response(
        request,
        exc.status_code,
        detail.get("code", "HTTP_" + str(exc.status_code)),
        detail.get("message", "Request rejected"),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error_response(
        request, 422, "VALIDATION_ERROR", "Request does not match the API contract"
    )


@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError):
    return error_response(request, exc.http_status, exc.code, exc.message)


@app.get("/health/live")
@app.get("/v1/health/live", include_in_schema=False)
@app.get("/api/v1/health/live", include_in_schema=False)
def live():
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/v1/health/ready", include_in_schema=False)
@app.get("/api/v1/health/ready", include_in_schema=False)
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "0010":
                raise RuntimeError("Migration pending")
        Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2).ping()
    except Exception as exc:
        raise HTTPException(503, "Critical dependency is unavailable") from exc
    return {
        "status": "ready",
        "version": settings.build_version,
        "migration": revision,
        "payment_mode": settings.payment_mode,
    }


app.include_router(router, prefix="/api/v1")
app.include_router(router, prefix="/v1", include_in_schema=False)

app.include_router(operations_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/v1", include_in_schema=False)


app.include_router(realtime_router, prefix="/api/v1")


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.getLogger("larimia.requests").handlers = [handler]
logging.getLogger("larimia.requests").setLevel(logging.INFO)
logging.getLogger("larimia.requests").propagate = False
app.add_middleware(RequestLimits)


FastAPIInstrumentor.instrument_app(app, excluded_urls="health/live")
SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=False)


app.include_router(notification_router, prefix="/api/v1")

app.include_router(job_router, prefix="/api/v1")

app.include_router(account_router, prefix="/api/v1")
