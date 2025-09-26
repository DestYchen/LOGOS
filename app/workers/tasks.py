from __future__ import annotations

import asyncio
import uuid

from celery.utils.log import get_task_logger

from app.services import pipeline
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

_worker_loop = asyncio.new_event_loop()


@celery_app.task(name="supplyhub.process_batch")
def process_batch(batch_id: str) -> None:
    logger.info("Processing batch %s", batch_id)
    _worker_loop.run_until_complete(pipeline.run_batch_pipeline(uuid.UUID(batch_id)))


@celery_app.task(name="supplyhub.validate_batch")
def validate_batch(batch_id: str) -> None:
    logger.info("Validating batch %s", batch_id)
    _worker_loop.run_until_complete(pipeline.run_validation_pipeline(uuid.UUID(batch_id)))
