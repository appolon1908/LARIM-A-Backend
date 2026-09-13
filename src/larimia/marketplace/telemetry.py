from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from larimia.config import get_settings


def setup():
    settings = get_settings()
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "larimia-api",
                "service.version": settings.build_version,
                "deployment.environment.name": settings.env,
            }
        )
    )
    if settings.telemetry_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.telemetry_otlp_endpoint, timeout=2)
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter, max_queue_size=1024, max_export_batch_size=128, export_timeout_millis=2000
            )
        )
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()

    def redact_redis(span, instance, args, kwargs):
        if span and span.is_recording():
            command = str(args[0]).split(" ", 1)[0] if args else "REDIS"
            span.set_attribute("db.statement", command)
            span.set_attribute("db.query.text", command)

    RedisInstrumentor().instrument(request_hook=redact_redis)
