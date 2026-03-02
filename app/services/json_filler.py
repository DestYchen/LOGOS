from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.core.config import get_settings
from app.core.enums import DocumentType
from app.core.schema import get_schema
from app.services import local_archive

settings = get_settings()
logger = logging.getLogger(__name__)
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F]")
_LATIN_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")


def _strip_cyrillic_words(text: str) -> str:
    if not text:
        return ""
    parts: List[str] = []
    for raw in text.split():
        if not raw:
            continue
        if not _CYRILLIC_RE.search(raw):
            parts.append(raw)
            continue
        if _LATIN_OR_DIGIT_RE.search(raw):
            cleaned = _CYRILLIC_RE.sub("", raw).strip()
            if cleaned:
                parts.append(cleaned)
    return " ".join(parts).strip()


def _filter_specification_tokens(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        text = token.get("text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)
        if not text:
            continue
        cleaned = _strip_cyrillic_words(text)
        if not cleaned:
            continue
        if cleaned == text:
            filtered.append(token)
            continue
        cleaned_token = dict(token)
        cleaned_token["text"] = cleaned
        filtered.append(cleaned_token)
    return filtered


async def fill_json(
    doc_id: uuid.UUID,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str] = None,
    ocr_tokens: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Send document text and OCR context to the json-filler service."""

    if settings.use_stub_services:
        return _stub_fill_json(doc_id, doc_type, doc_text)

    payload: Dict[str, Any] = {
        "doc_id": str(doc_id),
        "doc_type": doc_type.value,
        "doc_text": doc_text,
    }
    if file_name:
        payload["file_name"] = file_name
    if ocr_tokens is not None:
        tokens_list = list(ocr_tokens)
        if doc_type == DocumentType.SPECIFICATION:
            tokens_list = _filter_specification_tokens(tokens_list)
        payload["tokens"] = tokens_list

    if local_archive.enabled():
        local_archive.write_api_request(
            doc_id=str(doc_id),
            doc_type=doc_type,
            request_kind="local",
            attempt=1,
            payload={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": "local_http",
                "doc_id": str(doc_id),
                "doc_type": doc_type.value,
                "file_name": file_name,
                "endpoint": str(settings.json_filler_endpoint),
                "timeout": 120.0,
                "payload": payload,
            },
        )
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(str(settings.json_filler_endpoint), json=payload)
            response.raise_for_status()
            result = response.json()
            if local_archive.enabled():
                local_archive.write_api_response(
                    doc_id=str(doc_id),
                    doc_type=doc_type,
                    request_kind="local",
                    attempt=1,
                    payload={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "provider": "local_http",
                        "doc_id": str(doc_id),
                        "doc_type": doc_type.value,
                        "file_name": file_name,
                        "response": result,
                    },
                )
            return result
        except httpx.HTTPError:
            if settings.use_stub_services:
                logger.warning(
                    "JSON filler HTTP error; using stubbed response for %s", doc_id, exc_info=True
                )
                stub = _stub_fill_json(doc_id, doc_type, doc_text)
                if local_archive.enabled():
                    local_archive.write_api_response(
                        doc_id=str(doc_id),
                        doc_type=doc_type,
                        request_kind="local",
                        attempt=1,
                        payload={
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "provider": "local_http",
                            "doc_id": str(doc_id),
                            "doc_type": doc_type.value,
                            "file_name": file_name,
                            "response": stub,
                            "error": "http_error_stub",
                        },
                    )
                return stub
            raise


def _stub_fill_json(doc_id: uuid.UUID, doc_type: DocumentType, doc_text: str) -> Dict[str, Any]:
    schema = get_schema(doc_type)
    words = [word for word in doc_text.split() if word]
    fields: Dict[str, Dict[str, Any]] = {}
    for idx, (key, field_schema) in enumerate(schema.fields.items()):
        value = words[idx % len(words)] if words else f"{key}_stub"
        fields[key] = {
            "value": value,
            "source": "stub",
            "page": 1,
            "bbox": [],
            "token_refs": [],
            "required": field_schema.required,
        }

    if not fields:
        trimmed = doc_text.strip()[:256]
        fields["raw_text"] = {
            "value": trimmed or "stub",
            "source": "stub",
            "page": 1,
            "bbox": [],
            "token_refs": [],
            "required": False,
        }

    return {
        "doc_id": str(doc_id),
        "doc_type": doc_type.value,
        "fields": fields,
        "meta": {"stub": True},
    }
