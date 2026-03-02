from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

from app.core.config import get_settings
from app.core.enums import DocumentType
from app.services import json_filler, json_filler_remote

logger = logging.getLogger(__name__)
settings = get_settings()

_CACHED_TYPES: Set[DocumentType] = set()
_CACHED_MTIME: float | None = None


def _parse_remote_types(path: Path) -> Set[DocumentType]:
    types: Set[DocumentType] = set()
    if not path.exists():
        return types
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        doc_type = DocumentType.__members__.get(line)
        if not doc_type:
            logger.warning("Unknown remote doc type in %s: %s", path, line)
            continue
        types.add(doc_type)
    return types


def remote_doc_types() -> Set[DocumentType]:
    global _CACHED_MTIME, _CACHED_TYPES
    path = settings.remote_json_filler_types_path
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        mtime = None
    if _CACHED_MTIME != mtime:
        _CACHED_TYPES = _parse_remote_types(path)
        _CACHED_MTIME = mtime
    return _CACHED_TYPES


def is_remote_doc_type(doc_type: DocumentType) -> bool:
    return doc_type in remote_doc_types()


def _is_stub_response(payload: Dict[str, Any]) -> bool:
    meta = payload.get("meta")
    if isinstance(meta, dict) and meta.get("stub") is True:
        return True
    return payload.get("stub") is True


async def _fallback_local(
    doc_id,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str],
    ocr_tokens: Optional[Iterable[Dict[str, Any]]],
    *,
    reason: str,
    fallback_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        logger.warning("Falling back to local JSON filler (%s) for %s", reason, doc_id)
        return await json_filler.fill_json(
            doc_id,
            doc_type,
            doc_text=doc_text,
            file_name=file_name,
            ocr_tokens=ocr_tokens,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Local JSON filler failed after fallback for %s", doc_id, exc_info=True)
        if fallback_response is not None:
            return fallback_response
        return json_filler_remote._stub_fill_json(doc_id, doc_type, doc_text)


async def _fill_remote_with_fallback(
    doc_id,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str],
    ocr_tokens: Optional[Iterable[Dict[str, Any]]],
) -> Dict[str, Any]:
    timeout = float(settings.remote_json_filler_fallback_timeout)
    try:
        remote_call = json_filler_remote.fill_json(
            doc_id,
            doc_type,
            doc_text=doc_text,
            file_name=file_name,
            ocr_tokens=ocr_tokens,
        )
        if timeout > 0:
            response = await asyncio.wait_for(remote_call, timeout=timeout)
        else:
            response = await remote_call
    except asyncio.TimeoutError:
        return await _fallback_local(
            doc_id,
            doc_type,
            doc_text,
            file_name,
            ocr_tokens,
            reason=f"timeout_{timeout}s",
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return await _fallback_local(
            doc_id,
            doc_type,
            doc_text,
            file_name,
            ocr_tokens,
            reason="remote_error",
        )

    if _is_stub_response(response):
        return await _fallback_local(
            doc_id,
            doc_type,
            doc_text,
            file_name,
            ocr_tokens,
            reason="remote_stub",
            fallback_response=response,
        )
    return response


async def fill_json(
    doc_id,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str] = None,
    ocr_tokens: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if is_remote_doc_type(doc_type):
        return await _fill_remote_with_fallback(
            doc_id,
            doc_type,
            doc_text,
            file_name,
            ocr_tokens,
        )
    return await json_filler.fill_json(
        doc_id,
        doc_type,
        doc_text=doc_text,
        file_name=file_name,
        ocr_tokens=ocr_tokens,
    )
