from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import get_session
from app.core.enums import BatchStatus, DocumentType
from app.core.storage import ensure_base_dir, feedback_root
from app.models import Batch, Document
from app.services import batches as batch_service
from app.services.feedback import (
    TELEGRAM_BOT_TOKEN_OVERRIDE,
    TELEGRAM_CHAT_ID_OVERRIDE,
)

logger = logging.getLogger(__name__)

UTC_PLUS_3 = timezone(timedelta(hours=3))
MESSAGE_CHUNK_LIMIT = 3900
STATE_FILE_NAME = "daily_summary_state.json"

_INTERNAL_DOC_TYPES = {
    DocumentType.CONTRACT_1,
    DocumentType.CONTRACT_2,
    DocumentType.CONTRACT_3,
}


@dataclass(frozen=True)
class PackStats:
    batch_id: str
    pack_name: str
    non_empty_fields: int
    empty_fields: int
    completion_pct: float
    manual_changed_fields: int


def _period_utc_for_local_day(day_local: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day_local, time.min, tzinfo=UTC_PLUS_3)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _state_file() -> Path:
    ensure_base_dir()
    return feedback_root() / STATE_FILE_NAME


def _load_state() -> Dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read daily summary state file: %s", path, exc_info=True)
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    path = _state_file()
    try:
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("Failed to write daily summary state file: %s", path, exc_info=True)


def _already_sent(day_local: date) -> bool:
    state = _load_state()
    return state.get("last_sent_day") == day_local.isoformat()


def _mark_sent(day_local: date) -> None:
    state = _load_state()
    state["last_sent_day"] = day_local.isoformat()
    state["last_sent_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


def _is_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _normalize_pack_name(batch: Batch) -> str:
    title = batch_service.extract_batch_title(batch)
    if title:
        return " ".join(title.split())
    return f"Batch {str(batch.id)[:8]}"


def _collect_pack_stats(batch: Batch) -> PackStats:
    non_empty = 0
    empty = 0
    manual_changed_keys: set[tuple[str, str]] = set()

    for document in batch.documents:
        if document.doc_type in _INTERNAL_DOC_TYPES:
            continue

        for field in document.fields:
            if field.latest:
                if _is_non_empty_value(field.value):
                    non_empty += 1
                else:
                    empty += 1
            if (field.edited_by or str(field.source).lower() == "user") and int(field.version or 0) > 1:
                manual_changed_keys.add((str(document.id), field.field_key))

    total = non_empty + empty
    completion_pct = round((non_empty / total) * 100, 1) if total else 0.0
    return PackStats(
        batch_id=str(batch.id),
        pack_name=_normalize_pack_name(batch),
        non_empty_fields=non_empty,
        empty_fields=empty,
        completion_pct=completion_pct,
        manual_changed_fields=len(manual_changed_keys),
    )


async def _load_done_batches_for_period(
    session: AsyncSession,
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> List[Batch]:
    stmt = (
        select(Batch)
        .where(
            Batch.status == BatchStatus.DONE,
            Batch.updated_at >= start_utc,
            Batch.updated_at < end_utc,
        )
        .options(selectinload(Batch.documents).selectinload(Document.fields))
        .order_by(Batch.updated_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _format_summary(day_local: date, stats: List[PackStats]) -> str:
    lines = [
        f"Daily pack summary for {day_local.isoformat()} (UTC+3)",
        f"Processed packs: {len(stats)}",
        "",
    ]
    if not stats:
        lines.append("No processed packs for this period.")
        return "\n".join(lines)

    for index, item in enumerate(stats, start=1):
        lines.append(
            f"{index}. {item.pack_name} [{item.batch_id[:8]}] | "
            f"non-empty: {item.non_empty_fields} | "
            f"empty: {item.empty_fields} | "
            f"fill: {item.completion_pct:.1f}% | "
            f"manual changes: {item.manual_changed_fields}"
        )
    return "\n".join(lines)


def _split_message(text: str, limit: int = MESSAGE_CHUNK_LIMIT) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(line) <= limit:
            current = line
            continue
        start = 0
        while start < len(line):
            end = start + limit
            chunks.append(line[start:end])
            start = end
    if current:
        chunks.append(current)
    return chunks if chunks else [text[:limit]]


async def _send_telegram_text(text: str) -> bool:
    settings = get_settings()
    token = TELEGRAM_BOT_TOKEN_OVERRIDE or settings.telegram_bot_token
    chat_id = TELEGRAM_CHAT_ID_OVERRIDE or settings.telegram_chat_id
    if not token or not chat_id:
        logger.warning("Telegram daily summary is disabled: missing token or chat id.")
        return False

    base_url = f"https://api.telegram.org/bot{token}"
    chunks = _split_message(text)

    async with httpx.AsyncClient(timeout=10) as client:
        for idx, chunk in enumerate(chunks, start=1):
            body = chunk if len(chunks) == 1 else f"[{idx}/{len(chunks)}]\n{chunk}"
            response = await client.post(
                f"{base_url}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": body,
                    "disable_web_page_preview": True,
                },
            )
            if not response.is_success:
                logger.warning("Telegram daily summary sendMessage failed: %s", response.text)
                return False
            payload = response.json()
            if not payload.get("ok"):
                logger.warning("Telegram daily summary sendMessage failed: %s", response.text)
                return False
    return True


async def send_daily_summary_for_day(day_local: date, *, force: bool = False) -> bool:
    if not force and _already_sent(day_local):
        logger.info("Daily summary already sent for %s", day_local.isoformat())
        return False

    start_utc, end_utc = _period_utc_for_local_day(day_local)
    async with get_session() as session:
        batches = await _load_done_batches_for_period(session, start_utc=start_utc, end_utc=end_utc)

    stats = [_collect_pack_stats(batch) for batch in batches]
    message = _format_summary(day_local, stats)
    sent = await _send_telegram_text(message)
    if sent:
        _mark_sent(day_local)
        logger.info(
            "Daily summary sent for %s (packs=%s)",
            day_local.isoformat(),
            len(stats),
        )
    return sent


async def send_daily_summary_for_previous_day(*, force: bool = False) -> bool:
    today_local = datetime.now(UTC_PLUS_3).date()
    previous_day = today_local - timedelta(days=1)
    return await send_daily_summary_for_day(previous_day, force=force)
