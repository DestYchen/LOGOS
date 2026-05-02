from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.core.enums import DocumentType
from app.services.dots_ocr_adapter import get_dots_ocr_adapter


logger = logging.getLogger(__name__)
settings = get_settings()

DOTS_BBOX_OCR_FILENAME = "dots_bbox_ocr.json"
_SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
_TASKS: Dict[Tuple[str, str], asyncio.Task[List[Dict[str, Any]]]] = {}

_BBOX_DOTS_PROMPT = (
    "Detect all visible text regions in this document page for later field bbox grounding.\n"
    "Return only a valid JSON array. No prose, markdown, or comments.\n"
    "Each item must contain exactly: bbox, category, text.\n"
    "bbox format is [x1, y1, x2, y2] in image coordinates.\n"
    "Use small useful regions: text lines, table cells, labels with adjacent values only when they are inseparable.\n"
    "For tables, prefer one item per visible table cell or compact row cell, not one huge table bbox.\n"
    "Keep the original text exactly as written; do not translate or normalize.\n"
    "Sort items in human reading order."
)


def enabled() -> bool:
    return bool(settings.field_bbox_grounding_enabled)


def cache_path(derived_dir: Path) -> Path:
    return derived_dir / DOTS_BBOX_OCR_FILENAME


def start_dots_bbox_ocr(
    *,
    batch_id: uuid.UUID,
    doc_id: uuid.UUID,
    file_path: Path,
    cache_file: Path,
) -> None:
    if not enabled():
        return
    if not _supported_file(file_path):
        return
    if cache_file.exists():
        return

    key = _task_key(batch_id, doc_id)
    existing = _TASKS.get(key)
    if existing is not None and not existing.done():
        return

    task = asyncio.create_task(
        _run_dots_bbox_ocr(doc_id=doc_id, file_path=file_path, cache_file=cache_file),
        name=f"dots-bbox-grounding-{doc_id}",
    )
    _TASKS[key] = task

    def _cleanup(done: asyncio.Task[List[Dict[str, Any]]]) -> None:
        current = _TASKS.get(key)
        if current is done:
            _TASKS.pop(key, None)
        if not done.cancelled():
            try:
                done.exception()
            except Exception:
                logger.debug("Dots bbox grounding OCR task failed for doc=%s", doc_id, exc_info=True)

    task.add_done_callback(_cleanup)


async def get_dots_bbox_tokens(
    *,
    batch_id: uuid.UUID,
    doc_id: uuid.UUID,
    cache_file: Path,
    file_path: Optional[Path] = None,
    allow_sync_run: bool = True,
) -> List[Dict[str, Any]]:
    if not enabled():
        return []

    key = _task_key(batch_id, doc_id)
    task = _TASKS.get(key)
    if task is not None:
        done, _pending = await asyncio.wait({task}, timeout=max(settings.field_bbox_grounding_dots_timeout, 1))
        if done:
            try:
                return await task
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Dots bbox grounding OCR failed for doc=%s", doc_id, exc_info=True)
                return read_cached_tokens(cache_file)
        logger.warning("Dots bbox grounding OCR timed out for doc=%s", doc_id)
        return read_cached_tokens(cache_file)

    cached = read_cached_tokens(cache_file)
    if cached:
        return cached

    if allow_sync_run and file_path is not None and _supported_file(file_path):
        try:
            return await _run_dots_bbox_ocr(doc_id=doc_id, file_path=file_path, cache_file=cache_file)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Synchronous Dots bbox grounding OCR failed for doc=%s", doc_id, exc_info=True)
            return read_cached_tokens(cache_file)

    return []


async def cancel_batch_tasks(batch_id: uuid.UUID) -> None:
    batch_key = str(batch_id)
    tasks = [task for key, task in list(_TASKS.items()) if key[0] == batch_key]
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def read_cached_tokens(cache_file: Path) -> List[Dict[str, Any]]:
    if not cache_file.exists():
        return []
    try:
        with cache_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        logger.debug("Failed to read Dots bbox cache %s", cache_file, exc_info=True)
        return []
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(tokens, list):
        return []
    return [_normalize_token(token, idx) for idx, token in enumerate(tokens) if isinstance(token, dict)]


def write_cached_tokens(
    *,
    cache_file: Path,
    doc_id: uuid.UUID,
    tokens: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "doc_id": str(doc_id),
        "tokens": tokens,
        "meta": {"source": "dots_bbox_grounding", **(meta or {})},
    }
    with cache_file.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


async def ground_fields(
    *,
    doc_id: uuid.UUID,
    doc_type: DocumentType,
    file_name: str,
    fields: Dict[str, Dict[str, Any]],
    dots_tokens: List[Dict[str, Any]],
) -> bool:
    if not enabled() or not fields:
        return False

    _clear_field_locations(fields)

    normalized_tokens = [
        _normalize_token(token, idx) for idx, token in enumerate(dots_tokens) if isinstance(token, dict)
    ]
    normalized_tokens = [token for token in normalized_tokens if _normalize_bbox(token.get("bbox"))]
    if not normalized_tokens:
        return False

    if not settings.field_bbox_grounding_openclaw_api_key:
        logger.warning("Field bbox grounding skipped: OpenClaw API key is not configured")
        return False

    prompt = _build_grounding_prompt(
        doc_type=doc_type,
        file_name=file_name,
        fields=fields,
        tokens=normalized_tokens,
    )

    try:
        raw = await _call_openclaw(prompt)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("OpenClaw field bbox grounding failed for doc=%s", doc_id, exc_info=True)
        return False

    payload, _repaired = _parse_json_payload(raw)
    refs_by_field = _extract_refs_by_field(payload)
    if not refs_by_field:
        return False

    token_map = {str(token.get("id")): token for token in normalized_tokens if token.get("id") is not None}
    changed = False
    for field_key, payload in fields.items():
        refs = _validate_refs(refs_by_field.get(field_key), normalized_tokens, token_map)
        if not refs:
            continue
        page, bbox = _derive_page_bbox(refs, token_map)
        if bbox is None:
            continue
        payload["token_refs"] = refs
        payload["page"] = page
        payload["bbox"] = bbox
        changed = True

    return changed


async def _run_dots_bbox_ocr(
    *,
    doc_id: uuid.UUID,
    file_path: Path,
    cache_file: Path,
) -> List[Dict[str, Any]]:
    adapter = await get_dots_ocr_adapter()
    options = {
        "dpi": settings.field_bbox_grounding_dots_dpi,
        "max_pixels": settings.field_bbox_grounding_dots_max_pixels,
        "max_completion_tokens": settings.field_bbox_grounding_dots_max_completion_tokens,
        "prompt_override": _BBOX_DOTS_PROMPT,
    }
    tokens = await adapter.run(doc_id, file_path, options=options)
    normalized = [_normalize_token(token, idx) for idx, token in enumerate(tokens) if isinstance(token, dict)]
    write_cached_tokens(cache_file=cache_file, doc_id=doc_id, tokens=normalized)
    logger.info("Dots bbox grounding OCR cached doc_id=%s tokens=%s", doc_id, len(normalized))
    return normalized


def _supported_file(file_path: Path) -> bool:
    return file_path.exists() and file_path.suffix.lower() in _SUPPORTED_SUFFIXES


def _task_key(batch_id: uuid.UUID, doc_id: uuid.UUID) -> Tuple[str, str]:
    return (str(batch_id), str(doc_id))


def _normalize_token(token: Dict[str, Any], idx: int) -> Dict[str, Any]:
    token_id = token.get("id")
    if token_id is None or str(token_id).strip() == "":
        token_id = f"bbox_t{idx}"
    try:
        page = int(token.get("page", 1) or 1)
    except (TypeError, ValueError):
        page = 1
    normalized = {
        "id": str(token_id),
        "text": str(token.get("text") or ""),
        "page": max(page, 1),
        "bbox": token.get("bbox") if isinstance(token.get("bbox"), list) else [],
        "category": str(token.get("category") or "Text"),
    }
    try:
        normalized["conf"] = float(token.get("conf", 0.0))
    except (TypeError, ValueError):
        normalized["conf"] = 0.0
    return normalized


def _clear_field_locations(fields: Dict[str, Dict[str, Any]]) -> None:
    for payload in fields.values():
        if not isinstance(payload, dict):
            continue
        payload["bbox"] = []
        payload["token_refs"] = []


def _build_grounding_prompt(
    *,
    doc_type: DocumentType,
    file_name: str,
    fields: Dict[str, Dict[str, Any]],
    tokens: List[Dict[str, Any]],
) -> str:
    field_items = []
    for key, payload in fields.items():
        value = payload.get("value") if isinstance(payload, dict) else None
        if value is None:
            continue
        value_text = str(value).strip()
        if not value_text:
            continue
        field_items.append({"field_key": key, "value": value_text})

    fields_json = json.dumps(field_items, ensure_ascii=False)
    if settings.field_bbox_grounding_max_fields_chars and len(fields_json) > settings.field_bbox_grounding_max_fields_chars:
        fields_json = fields_json[: settings.field_bbox_grounding_max_fields_chars]

    prompt_tokens = [
        {
            "id": token.get("id"),
            "text": token.get("text"),
            "page": token.get("page"),
            "bbox": token.get("bbox"),
            "category": token.get("category"),
            "conf": token.get("conf"),
        }
        for token in tokens
        if str(token.get("text") or "").strip()
    ]
    tokens_json = json.dumps(prompt_tokens, ensure_ascii=False)
    if settings.field_bbox_grounding_max_tokens_chars and len(tokens_json) > settings.field_bbox_grounding_max_tokens_chars:
        tokens_json = tokens_json[: settings.field_bbox_grounding_max_tokens_chars]

    return (
        "You assign bbox evidence to already-filled document fields.\n"
        "Return only strict JSON. No prose, markdown, or comments.\n"
        "The field values are immutable. Do not correct, rewrite, add, or remove field values.\n"
        "For each field, choose token ids from DOTS TOKENS that visually contain the exact field value.\n"
        "Use token ids only; never invent ids. If unsure, return [] for that field.\n"
        "For product/table fields, choose the smallest cell or row tokens that contain the specific value.\n"
        "Output shape must be: {\"fields\": {\"field.key\": {\"token_refs\": [\"token_id\"]}}}.\n\n"
        f"DOCUMENT TYPE:\n{doc_type.value}\n\n"
        f"FILE NAME:\n{file_name}\n\n"
        f"FILLED FIELDS:\n{fields_json}\n\n"
        f"DOTS TOKENS:\n{tokens_json}\n"
    )


async def _call_openclaw(prompt: str) -> str:
    payload = {
        "model": settings.field_bbox_grounding_openclaw_model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.field_bbox_grounding_openclaw_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=max(settings.field_bbox_grounding_openclaw_timeout, 1)) as client:
        response = await client.post(settings.field_bbox_grounding_openclaw_base_url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    return _extract_response_text(data)


def _extract_response_text(data: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(str(content.get("text", "")))
    if chunks:
        return "\n".join(part for part in chunks if part)
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text
    return ""


def _parse_json_payload(raw: str) -> Tuple[Dict[str, Any], bool]:
    if not raw:
        return {}, False
    extracted = _extract_json(raw)
    for candidate, repaired in (
        (extracted, False),
        (_sanitize_json_like(extracted), True),
    ):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return (data if isinstance(data, dict) else {}, repaired)
    return {}, False


def _extract_json(payload: str) -> str:
    cleaned = _strip_markdown_fence(payload)
    try:
        json.loads(cleaned)
        return cleaned
    except Exception:
        pass
    for candidate in _iter_json_fragments(cleaned):
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return candidate
    return cleaned


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _iter_json_fragments(text: str) -> Iterator[str]:
    starts = [idx for idx, char in enumerate(text) if char == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            char = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : idx + 1]
                    break


def _sanitize_json_like(text: str) -> str:
    sanitized = text.strip()
    sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
    return sanitized


def _extract_refs_by_field(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_fields = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(raw_fields, dict):
        raw_fields = payload
    refs_by_field: Dict[str, Any] = {}
    for key, value in raw_fields.items():
        if isinstance(value, dict):
            refs_by_field[str(key)] = value.get("token_refs", value.get("refs", []))
        else:
            refs_by_field[str(key)] = value
    return refs_by_field


def _validate_refs(
    raw_refs: Any,
    tokens: List[Dict[str, Any]],
    token_map: Dict[str, Dict[str, Any]],
) -> List[str]:
    if raw_refs is None:
        return []
    if not isinstance(raw_refs, list):
        raw_refs = [raw_refs]
    refs: List[str] = []
    for ref in raw_refs:
        ref_id = str(ref).strip()
        if not ref_id:
            continue
        if ref_id in token_map:
            refs.append(ref_id)
            continue
        try:
            idx = int(ref_id)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(tokens):
            token_id = str(tokens[idx].get("id") or "")
            if token_id and token_id in token_map:
                refs.append(token_id)
    seen: set[str] = set()
    unique: List[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        unique.append(ref)
    return unique


def _derive_page_bbox(
    refs: List[str],
    token_map: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[int], Optional[List[float]]]:
    candidates: List[Tuple[int, List[float]]] = []
    for ref in refs:
        token = token_map.get(ref)
        if not token:
            continue
        bbox = _normalize_bbox(token.get("bbox"))
        if not bbox:
            continue
        try:
            page = int(token.get("page", 1) or 1)
        except (TypeError, ValueError):
            page = 1
        candidates.append((max(page, 1), bbox))
    if not candidates:
        return None, None

    counts: Dict[int, int] = {}
    for page, _bbox in candidates:
        counts[page] = counts.get(page, 0) + 1
    top_count = max(counts.values())
    page = min(candidate for candidate, count in counts.items() if count == top_count)
    page_boxes = [bbox for candidate_page, bbox in candidates if candidate_page == page]
    return page, [
        min(bbox[0] for bbox in page_boxes),
        min(bbox[1] for bbox in page_boxes),
        max(bbox[2] for bbox in page_boxes),
        max(bbox[3] for bbox in page_boxes),
    ]


def _normalize_bbox(bbox: Any) -> Optional[List[float]]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        normalized = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if all(value == 0 for value in normalized):
        return None
    return normalized
