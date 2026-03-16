from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "supplyhub",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_max_tasks_per_child=100,
    beat_schedule={
        # 09:00 UTC equals 12:00 (midday) in UTC+3.
        "daily-telegram-pack-summary": {
            "task": "supplyhub.send_daily_summary",
            "schedule": crontab(minute=0, hour=9),
        },
    },
)

celery_app.autodiscover_tasks(["app.workers.tasks"])
