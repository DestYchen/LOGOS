from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.core.config import get_settings
from app.core.enums import DocumentType
from app.core.storage import unique_filename

logger = logging.getLogger(__name__)
settings = get_settings()

_BATCH_NAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def enabled() -> bool:
    return bool(settings.local_archive_mode)


def _doc_type_name(doc_type: DocumentType | str) -> str:
    if isinstance(doc_type, DocumentType):
        return doc_type.value
    return str(doc_type)


def _safe_batch_name(title: Optional[str], batch_id: str) -> str:
    base = (title or "").strip() or "batch"
    base = _BATCH_NAME_SAFE.sub("_", base).strip("._-")
    if not base:
        base = "batch"
    return f"{base}__{batch_id}"


def _batch_root(batch_id: str, batch_title: Optional[str]) -> Path:
    return settings.local_archive_dir / _safe_batch_name(batch_title, batch_id)


def _find_doc_dir(doc_id: str) -> Optional[Path]:
    root = settings.local_archive_dir
    if not root.exists():
        return None
    try:
        for batch_dir in root.iterdir():
            if not batch_dir.is_dir():
                continue
            candidate = batch_dir / "filler" / doc_id
            if candidate.exists():
                return candidate
    except Exception:
        return None
    return None


def _resolve_doc_dir(doc_id: str, batch_id: Optional[str], batch_title: Optional[str]) -> Path:
    if batch_id:
        return _batch_root(batch_id, batch_title) / "filler" / doc_id
    found = _find_doc_dir(doc_id)
    if found is not None:
        return found
    return settings.local_archive_dir / "unknown_batch" / "filler" / doc_id


def _write_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except TypeError:
        with path.open("w", encoding="utf-8") as handle:
            handle.write(str(payload))


def store_raw_file(*, batch_id: str, batch_title: Optional[str], source_path: Path) -> None:
    if not enabled():
        return
    try:
        batch_root = _batch_root(batch_id, batch_title)
        raw_dir = batch_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        target_name = unique_filename(raw_dir, source_path.name)
        shutil.copy2(source_path, raw_dir / target_name)
    except Exception:
        logger.warning("Local archive raw copy failed for %s", source_path, exc_info=True)


def write_filler_request(
    *,
    batch_id: str,
    batch_title: Optional[str],
    doc_id: str,
    doc_type: DocumentType | str,
    file_name: str,
    doc_text: str,
    ocr_tokens: Optional[Iterable[Dict[str, Any]]],
    source: str,
) -> None:
    if not enabled():
        return
    try:
        doc_type_name = _doc_type_name(doc_type)
        request_path = _resolve_doc_dir(doc_id, batch_id, batch_title) / f"{doc_type_name}.txt"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "doc_id": doc_id,
            "doc_type": doc_type_name,
            "file_name": file_name,
            "doc_text": doc_text,
            "ocr_tokens": list(ocr_tokens) if ocr_tokens is not None else None,
        }
        _write_payload(request_path, payload)
    except Exception:
        logger.warning("Local archive request write failed for %s", file_name, exc_info=True)


def write_filler_response(
    *,
    batch_id: str,
    batch_title: Optional[str],
    doc_id: str,
    doc_type: DocumentType | str,
    file_name: str,
    response: Dict[str, Any],
    source: str,
) -> None:
    if not enabled():
        return
    try:
        doc_type_name = _doc_type_name(doc_type)
        response_path = _resolve_doc_dir(doc_id, batch_id, batch_title) / f"{doc_type_name}__response.txt"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "doc_id": doc_id,
            "doc_type": doc_type_name,
            "file_name": file_name,
            "response": response,
        }
        _write_payload(response_path, payload)
    except Exception:
        logger.warning("Local archive response write failed for %s", file_name, exc_info=True)


def write_api_request(
    *,
    doc_id: str,
    doc_type: DocumentType | str,
    request_kind: str,
    attempt: int,
    payload: Dict[str, Any],
    batch_id: Optional[str] = None,
    batch_title: Optional[str] = None,
) -> None:
    if not enabled():
        return
    try:
        doc_type_name = _doc_type_name(doc_type)
        suffix = f"__api_request_{request_kind}"
        if attempt > 1:
            suffix += f"__attempt{attempt}"
        request_path = _resolve_doc_dir(doc_id, batch_id, batch_title) / f"{doc_type_name}{suffix}.txt"
        _write_payload(request_path, payload)
    except Exception:
        logger.warning("Local archive API request write failed for %s", doc_id, exc_info=True)


def write_api_response(
    *,
    doc_id: str,
    doc_type: DocumentType | str,
    request_kind: str,
    attempt: int,
    payload: Dict[str, Any],
    batch_id: Optional[str] = None,
    batch_title: Optional[str] = None,
) -> None:
    if not enabled():
        return
    try:
        doc_type_name = _doc_type_name(doc_type)
        suffix = f"__api_response_{request_kind}"
        if attempt > 1:
            suffix += f"__attempt{attempt}"
        response_path = _resolve_doc_dir(doc_id, batch_id, batch_title) / f"{doc_type_name}{suffix}.txt"
        _write_payload(response_path, payload)
    except Exception:
        logger.warning("Local archive API response write failed for %s", doc_id, exc_info=True)
