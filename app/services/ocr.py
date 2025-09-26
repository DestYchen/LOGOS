from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List

import httpx

from app.core.config import get_settings
from app.services import text_extractor

settings = get_settings()
logger = logging.getLogger(__name__)


async def run_ocr(
    doc_id: uuid.UUID,
    file_path: Path,
    *,
    file_name: str | None = None,
    languages: Iterable[str] = ("zh", "en", "ru"),
    options: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if settings.use_stub_services:
        return _stub_ocr(doc_id, file_path)

    payload = {
        "doc_id": str(doc_id),
        "file_path": str(file_path),
        "langs": list(languages),
        "options": options or {"layout": True, "tables": True},
    }
    if file_name:
        payload["file_name"] = file_name
    try:
        file_bytes = file_path.read_bytes()
    except Exception:
        file_bytes = None
    if file_bytes is not None:
        payload["file_bytes"] = base64.b64encode(file_bytes).decode("ascii")
        payload["file_suffix"] = file_path.suffix
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(str(settings.ocr_endpoint), json=payload)
            response.raise_for_status()
            raw = response.json()
            return _normalize_payload(raw, str(doc_id))
        except httpx.HTTPError:
            if settings.use_stub_services:
                logger.warning("OCR HTTP error; using stubbed response for %s", file_path, exc_info=True)
                return _stub_ocr(doc_id, file_path)
            raise


def _normalize_payload(raw: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    tokens_raw: List[Dict[str, Any]] = []
    if "tokens" in raw and isinstance(raw["tokens"], list):
        tokens_raw = raw["tokens"]
    else:
        for page in raw.get("pages", []):
            tokens_raw.extend(page.get("tokens", []))

    tokens: List[Dict[str, Any]] = []
    for idx, token in enumerate(tokens_raw):
        text = token.get("text", "")
        if not text:
            continue
        normalized: Dict[str, Any] = {
            "id": token.get("id", f"t_{idx}"),
            "text": text,
            "conf": float(token.get("conf", 0.0)),
            "bbox": token.get("bbox", [0, 0, 0, 0]),
        }
        if "page" in token and token["page"] is not None:
            normalized["page"] = token["page"]
        if "category" in token and token["category"]:
            normalized["category"] = token["category"]
        tokens.append(normalized)

    return {"doc_id": raw.get("doc_id", doc_id), "tokens": tokens}


def _stub_ocr(doc_id: uuid.UUID, file_path: Path) -> Dict[str, Any]:
    extraction = text_extractor.extract_text(file_path)
    text = extraction.text if extraction else _read_text(file_path)
    tokens = _text_to_tokens(text)
    return {"doc_id": str(doc_id), "tokens": tokens}


def _text_to_tokens(text: str) -> List[Dict[str, Any]]:
    tokens: List[Dict[str, Any]] = []
    for idx, word in enumerate(text.split()[:500]):
        if not word:
            continue
        tokens.append(
            {
                "id": f"stub_t{idx}",
                "text": word,
                "conf": 1.0,
                "page": 1,
                "bbox": [0, 0, 0, 0],
                "category": "Text",
            }
        )
    return tokens


def _read_text(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception:
        logger.debug("Failed to read %s as UTF-8; returning empty text", file_path, exc_info=True)
        return ""
