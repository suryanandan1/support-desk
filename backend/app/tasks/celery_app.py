"""Celery application. Broker: Redis (Memurai on Windows) at REDIS_URL.

Start a worker from the backend folder (Windows needs the solo pool):
    celery -A app.tasks.celery_app worker --pool=solo --loglevel=INFO
"""

from typing import Any

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()

celery_app = Celery("support", broker=settings.redis_url, include=["app.tasks.document_tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    # Job status is tracked on the Document row, so no result backend is needed.
    task_ignore_result=True,
    # Acknowledge after the task finishes: a crashed worker's job is redelivered.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    # Fail fast when Redis is down instead of blocking the upload request.
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 10},
    task_publish_retry_policy={
        "max_retries": 2,
        "interval_start": 0,
        "interval_step": 0.5,
        "interval_max": 1,
    },
    task_always_eager=settings.celery_task_always_eager,
    worker_hijack_root_logger=False,
)


@celery_setup_logging.connect
def _configure_worker_logging(**_kwargs: Any) -> None:
    # Same formatter (with secret redaction) as the API process.
    setup_logging(settings.log_level, settings.log_json)
