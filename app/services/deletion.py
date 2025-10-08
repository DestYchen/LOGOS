from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List

from app.core.database import get_session
from app.core.enums import BatchStatus
from app.core.storage import remove_batch
from app.models import Batch, Document
from app.services import batches as batch_service
from app.services import pipeline
from app.services import tasks as task_tracker
from app.workers.celery_app import celery_app
from sqlalchemy import func, select

logger = logging.getLogger(__name__)

FINAL_STATUSES = {BatchStatus.DONE, BatchStatus.FAILED, BatchStatus.CANCELLED}


class BatchNotFoundError(Exception):
    """Raised when the requested batch does not exist."""


async def _mark_cancel_requested(batch_id: uuid.UUID, *, actor: str | None) -> BatchStatus:
    async with get_session() as session:
        batch = await session.get(Batch, batch_id)
        if batch is None:
            raise BatchNotFoundError(str(batch_id))

        meta = dict(batch.meta or {})
        cancel_info = dict(meta.get("cancel_info") or {})
        cancel_info["requested_at"] = datetime.utcnow().isoformat() + "Z"
        if actor:
            cancel_info["requested_by"] = actor
        meta["cancel_info"] = cancel_info

        if batch.status not in FINAL_STATUSES:
            batch.status = BatchStatus.CANCEL_REQUESTED
        batch.meta = meta
        await session.flush()
        return batch.status


async def _cleanup_database(batch_id: uuid.UUID) -> Dict[str, Any]:
    async with get_session() as session:
        batch = await session.get(Batch, batch_id)
        if batch is None:
            raise BatchNotFoundError(str(batch_id))

        # Avoid async lazy-loading of relationship: count explicitly
        res = await session.execute(
            select(func.count(Document.id)).where(Document.batch_id == batch_id)
        )
        document_count = res.scalar_one()
        meta = dict(batch.meta or {})
        meta.pop("active_tasks", None)
        batch.meta = meta
        batch.status = BatchStatus.CANCELLED
        await session.flush()
        await session.delete(batch)
        await session.flush()

    try:
        remove_batch(str(batch_id))
    except Exception:
        logger.warning("Failed to remove files for batch %s", batch_id, exc_info=True)

    return {"batch_id": str(batch_id), "documents": document_count}


async def delete_batch(batch_id: uuid.UUID, *, requested_by: str | None = None) -> Dict[str, Any]:
    """Safely cancel processing and delete batch records and files."""

    status_before = await _mark_cancel_requested(batch_id, actor=requested_by)
    logger.info("Deletion requested for batch %s by %s (status %s)", batch_id, requested_by, status_before)

    active_tasks: List[Dict[str, Any]] = await task_tracker.list_tasks(batch_id)

    await pipeline.cancel_local_tasks(batch_id)

    for entry in active_tasks:
        if entry.get("transport") != "celery":
            continue
        task_id = entry.get("task_id")
        if not task_id:
            continue
        try:
            celery_app.control.revoke(task_id, terminate=True)
            logger.info("Revoked Celery task %s for batch %s", task_id, batch_id)
        except Exception:
            logger.warning("Failed to revoke Celery task %s for batch %s", task_id, batch_id, exc_info=True)
        await task_tracker.remove_task(batch_id, kind=entry.get("kind"), task_id=task_id)

    # Remove any leftover bookkeeping entries
    await task_tracker.clear_tasks(batch_id)

    result = await _cleanup_database(batch_id)
    logger.info("Batch %s deleted (documents=%s)", batch_id, result.get("documents"))
    return result


async def fetch_active_tasks(batch_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Return current task entries for diagnostics."""

    return await task_tracker.list_tasks(batch_id)


async def batch_exists(batch_id: uuid.UUID) -> bool:
    async with get_session() as session:
        return await session.get(Batch, batch_id) is not None

