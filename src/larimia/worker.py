import asyncio

from celery import Celery

from larimia.config import get_settings
from larimia.workers.inbox import process_batch
from larimia.workers.maintenance import expire_marketplace_state
from larimia.workers.outbox import publish_batch


settings = get_settings()

celery_app = Celery(
    "larimia",
    broker=settings.celery_broker_url,
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "publish-outbox": {
            "task": "larimia.publish_outbox",
            "schedule": 2.0,
        },
        "process-inbox": {
            "task": "larimia.process_inbox",
            "schedule": 2.0,
        },
        "expire-marketplace-state": {
            "task": "larimia.expire_marketplace_state",
            "schedule": 30.0,
        },
    },
)


@celery_app.task(name="larimia.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="larimia.publish_outbox")
def publish_outbox() -> int:
    return asyncio.run(publish_batch())


@celery_app.task(name="larimia.process_inbox")
def process_inbox() -> int:
    return process_batch()


@celery_app.task(name="larimia.expire_marketplace_state")
def expire_state() -> dict[str, int]:
    return expire_marketplace_state()
