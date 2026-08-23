import asyncio

from celery import Celery

from larimia.config import get_settings

settings = get_settings()

celery_app = Celery(
    "larimia",
    broker=settings.celery_broker_url,
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
)


@celery_app.task(name="larimia.ping")
def ping() -> str:
    return "pong"

from larimia.workers.outbox import publish_batch


@celery_app.task(name="larimia.publish_outbox")
def publish_outbox() -> int:
    return asyncio.run(publish_batch())
