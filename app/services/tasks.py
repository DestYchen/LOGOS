from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.database import get_session
from app.models import Batch

TaskEntry = Dict[str, Any]


def _ensure_list(value: Any) -> List[TaskEntry]:
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, dict)]
    return []


def _is_retryable_db_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "deadlock" in text
        or "could not serialize" in text
        or "lock timeout" in text
        or "timeout" in text
    )


async def record_task(
    batch_id: uuid.UUID,
    *,
    kind: str,
    transport: str,
    task_id: str,
) -> None:
    for attempt in range(5):
        try:
            async with get_session() as session:
                batch = await session.get(Batch, batch_id)
                if batch is None:
                    return

                meta = dict(batch.meta or {})
                current = _ensure_list(meta.get("active_tasks"))
                filtered: List[TaskEntry] = [
                    entry
                    for entry in current
                    if not (
                        entry.get("kind") == kind
                        and entry.get("transport") == transport
                    )
                ]
                filtered.append(
                    {
                        "kind": kind,
                        "transport": transport,
                        "task_id": task_id,
                        "created_at": datetime.utcnow().isoformat() + "Z",
                    }
                )
                meta["active_tasks"] = filtered
                batch.meta = meta
                await session.flush()
            return
        except (OperationalError, DBAPIError) as exc:
            if not _is_retryable_db_error(exc):
                raise
            await asyncio.sleep(0.05 * (2 ** attempt))


async def remove_task(
    batch_id: uuid.UUID,
    *,
    kind: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    for attempt in range(5):
        try:
            async with get_session() as session:
                batch = await session.get(Batch, batch_id)
                if batch is None:
                    return

                meta = dict(batch.meta or {})
                current = _ensure_list(meta.get("active_tasks"))
                if not current:
                    return

                filtered: List[TaskEntry] = []
                for entry in current:
                    entry_kind = entry.get("kind")
                    entry_task_id = entry.get("task_id")

                    kind_matches = kind is None or entry_kind == kind
                    task_matches = task_id is None or entry_task_id == task_id

                    if kind_matches and task_matches:
                        continue
                    filtered.append(entry)

                if filtered:
                    meta["active_tasks"] = filtered
                else:
                    meta.pop("active_tasks", None)
                batch.meta = meta
                await session.flush()
            return
        except (OperationalError, DBAPIError) as exc:
            if not _is_retryable_db_error(exc):
                raise
            await asyncio.sleep(0.05 * (2 ** attempt))


async def list_tasks(batch_id: uuid.UUID) -> List[TaskEntry]:
    async with get_session() as session:
        batch = await session.get(Batch, batch_id)
        if batch is None:
            return []

        return [dict(entry) for entry in _ensure_list((batch.meta or {}).get("active_tasks"))]


async def clear_tasks(batch_id: uuid.UUID) -> None:
    await remove_task(batch_id, kind=None, task_id=None)


