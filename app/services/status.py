from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BatchStatus, DocumentStatus
from app.models import Batch, Document, SystemStatusSnapshot


async def get_system_status(session: AsyncSession) -> dict:
    snapshot_stmt: Select = select(SystemStatusSnapshot).order_by(SystemStatusSnapshot.ts.desc()).limit(1)
    snapshot_result = await session.execute(snapshot_stmt)
    snapshot = snapshot_result.scalar_one_or_none()

    now = datetime.utcnow()
    if snapshot is not None:
        status = {
            "workers_busy": snapshot.workers_busy,
            "workers_total": snapshot.workers_total,
            "queue_depth": snapshot.queue_depth,
            "active_batches": snapshot.active_batches,
            "active_docs": snapshot.active_docs,
            "updated_at": snapshot.ts,
        }
    else:
        status = {
            "workers_busy": 0,
            "workers_total": 0,
            "queue_depth": 0,
            "active_batches": 0,
            "active_docs": 0,
            "updated_at": now,
        }

    active_batches_stmt = select(func.count(Batch.id)).where(Batch.status.notin_([BatchStatus.DONE, BatchStatus.FAILED, BatchStatus.CANCELLED]))
    active_batches = (await session.execute(active_batches_stmt)).scalar_one()
    status["active_batches"] = active_batches

    active_docs_stmt = select(func.count(Document.id)).where(
        Document.status.notin_([DocumentStatus.FILLED_REVIEWED, DocumentStatus.FAILED])
    )
    active_docs = (await session.execute(active_docs_stmt)).scalar_one()
    status["active_docs"] = active_docs

    return status


async def record_snapshot(
    session: AsyncSession,
    workers_busy: int,
    workers_total: int,
    queue_depth: int,
    active_batches: int,
    active_docs: int,
) -> None:
    snapshot = SystemStatusSnapshot(
        ts=datetime.utcnow(),
        workers_busy=workers_busy,
        workers_total=workers_total,
        queue_depth=queue_depth,
        active_batches=active_batches,
        active_docs=active_docs,
    )
    session.add(snapshot)
    await session.flush()
