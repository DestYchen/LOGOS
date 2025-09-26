from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Iterable, Optional

import httpx

from app.core.config import get_settings
from app.core.enums import DocumentType
from app.core.schema import get_schema

settings = get_settings()
logger = logging.getLogger(__name__)


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
        payload["tokens"] = list(ocr_tokens)

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(str(settings.json_filler_endpoint), json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            if settings.use_stub_services:
                logger.warning(
                    "JSON filler HTTP error; using stubbed response for %s", doc_id, exc_info=True
                )
                return _stub_fill_json(doc_id, doc_type, doc_text)
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
