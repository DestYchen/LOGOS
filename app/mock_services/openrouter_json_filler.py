from __future__ import annotations

import logging
import os
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.enums import DocumentType
from app.services import json_filler_remote

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
if OPENROUTER_API_KEY:
    json_filler_remote.HARDCODED_OPENROUTER_API_KEY = OPENROUTER_API_KEY

logger = logging.getLogger(__name__)

app = FastAPI(title="OpenRouter JSON Filler Adapter")


class FillerRequest(BaseModel):
    doc_id: str
    doc_type: str
    doc_text: str
    file_name: Optional[str] = None
    tokens: Optional[Any] = None


class FillerResponse(BaseModel):
    doc_id: str
    doc_type: str
    fields: Dict[str, Any]
    meta: Dict[str, Any] = {}


def _parse_doc_type(raw: str) -> DocumentType:
    token = (raw or "").strip()
    if not token:
        return DocumentType.UNKNOWN
    try:
        return DocumentType(token)
    except ValueError:
        member = DocumentType.__members__.get(token.upper()) or DocumentType.__members__.get(token)
        return member or DocumentType.UNKNOWN


def _parse_doc_id(raw: str) -> str | uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return str(raw)


def _normalize_tokens(tokens: Any, doc_text: str) -> List[Dict[str, Any]]:
    if isinstance(tokens, list):
        return [token for token in tokens if isinstance(token, dict)]
    if doc_text:
        return [
            {
                "id": "plain_text",
                "text": doc_text,
                "conf": 1.0,
                "page": 1,
                "bbox": [0, 0, 0, 0],
                "category": "Text",
            }
        ]
    return []


def _is_leaf_field(node: Any) -> bool:
    return isinstance(node, dict) and "value" in node


def _normalize_bbox(bbox: Any) -> Optional[List[float]]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None


def _bbox_missing(bbox: Any) -> bool:
    normalized = _normalize_bbox(bbox)
    if not normalized:
        return True
    return all(value == 0 for value in normalized)


def _token_page(token: Dict[str, Any]) -> Optional[int]:
    page = token.get("page")
    if page is None:
        return None
    try:
        return int(page)
    except (TypeError, ValueError):
        try:
            return int(float(page))
        except (TypeError, ValueError):
            return None


def _token_conf(token: Dict[str, Any]) -> Optional[float]:
    conf = token.get("conf")
    if conf is None:
        return None
    try:
        return float(conf)
    except (TypeError, ValueError):
        return None


def _normalize_token_refs(refs: Any) -> List[str]:
    if refs is None:
        return []
    if isinstance(refs, list):
        cleaned: List[str] = []
        for ref in refs:
            ref_str = "" if ref is None else str(ref).strip()
            if ref_str:
                cleaned.append(ref_str)
        return cleaned
    ref_str = str(refs).strip()
    return [ref_str] if ref_str else []


def _build_token_lookup(tokens: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for idx, token in enumerate(tokens):
        token_id = token.get("id")
        if token_id is not None:
            lookup[str(token_id)] = token
        lookup[str(idx)] = token
    return lookup


def _collect_ref_tokens(
    refs: List[str],
    tokens: List[Dict[str, Any]],
    lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    for ref in refs:
        token = lookup.get(ref)
        if token is None:
            try:
                idx = int(ref)
            except (TypeError, ValueError):
                idx = None
            if idx is not None and 0 <= idx < len(tokens):
                token = tokens[idx]
        if token is not None:
            collected.append(token)
    return collected


def _select_page(tokens: List[Dict[str, Any]], page_hint: Optional[int]) -> Optional[int]:
    pages = [page for page in (_token_page(token) for token in tokens) if page is not None]
    if not pages:
        return None
    if page_hint is not None and page_hint in pages:
        return page_hint
    counts = Counter(pages)
    top_count = max(counts.values())
    candidates = [page for page, count in counts.items() if count == top_count]
    return min(candidates) if candidates else None


def _merge_bboxes(tokens: List[Dict[str, Any]], page: Optional[int]) -> Optional[List[float]]:
    candidates: List[List[float]] = []
    for token in tokens:
        if page is not None and _token_page(token) != page:
            continue
        bbox = _normalize_bbox(token.get("bbox"))
        if bbox:
            candidates.append(bbox)
    if not candidates and page is not None:
        for token in tokens:
            bbox = _normalize_bbox(token.get("bbox"))
            if bbox:
                candidates.append(bbox)
    if not candidates:
        return None
    x1 = min(bbox[0] for bbox in candidates)
    y1 = min(bbox[1] for bbox in candidates)
    x2 = max(bbox[2] for bbox in candidates)
    y2 = max(bbox[3] for bbox in candidates)
    return [x1, y1, x2, y2]


def _average_confidence(tokens: List[Dict[str, Any]], page: Optional[int]) -> Optional[float]:
    values: List[float] = []
    for token in tokens:
        if page is not None and _token_page(token) != page:
            continue
        conf = _token_conf(token)
        if conf is not None:
            values.append(conf)
    if not values and page is not None:
        for token in tokens:
            conf = _token_conf(token)
            if conf is not None:
                values.append(conf)
    if not values:
        return None
    return sum(values) / len(values)


def _ensure_leaf_arrays(node: Any) -> None:
    if isinstance(node, dict):
        if _is_leaf_field(node):
            if not isinstance(node.get("bbox"), list):
                node["bbox"] = []
            if not isinstance(node.get("token_refs"), list):
                node["token_refs"] = []
        else:
            for value in node.values():
                _ensure_leaf_arrays(value)
    elif isinstance(node, list):
        for item in node:
            _ensure_leaf_arrays(item)


def _attach_token_metadata(node: Any, tokens: List[Dict[str, Any]], lookup: Dict[str, Dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if _is_leaf_field(node):
            refs = _normalize_token_refs(node.get("token_refs"))
            node["token_refs"] = refs
            if not refs:
                return
            ref_tokens = _collect_ref_tokens(refs, tokens, lookup)
            if not ref_tokens:
                return
            canonical_refs: List[str] = []
            for token in ref_tokens:
                token_id = token.get("id")
                if token_id is not None:
                    canonical_refs.append(str(token_id))
            if canonical_refs:
                node["token_refs"] = canonical_refs

            page_hint = node.get("page")
            try:
                page_hint_int = int(page_hint) if page_hint is not None else None
            except (TypeError, ValueError):
                page_hint_int = None
            page = _select_page(ref_tokens, page_hint_int)
            if page is not None and "page" not in node:
                node["page"] = page

            if _bbox_missing(node.get("bbox")):
                merged = _merge_bboxes(ref_tokens, page)
                if merged is not None:
                    node["bbox"] = merged

            if "confidence" not in node:
                conf = _average_confidence(ref_tokens, page)
                if conf is not None:
                    node["confidence"] = conf
        else:
            for value in node.values():
                _attach_token_metadata(value, tokens, lookup)
    elif isinstance(node, list):
        for item in node:
            _attach_token_metadata(item, tokens, lookup)


@app.post("/v1/fill", response_model=FillerResponse)
async def fill(request: FillerRequest) -> FillerResponse:
    doc_type = _parse_doc_type(request.doc_type)
    doc_id = _parse_doc_id(request.doc_id)
    tokens = _normalize_tokens(request.tokens, request.doc_text or "")

    logger.info(
        "Remote fill request doc_id=%s type=%s tokens=%s",
        request.doc_id,
        doc_type.value,
        len(tokens),
    )

    response = await json_filler_remote._fill_json_openrouter(
        doc_id,
        doc_type,
        doc_text=request.doc_text,
        file_name=request.file_name,
        ocr_tokens=tokens or None,
    )

    fields = response.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}

    if tokens:
        lookup = _build_token_lookup(tokens)
        _attach_token_metadata(fields, tokens, lookup)
    _ensure_leaf_arrays(fields)

    meta = dict(response.get("meta") or {})
    meta.setdefault("source", "openrouter-service")

    return FillerResponse(
        doc_id=str(request.doc_id),
        doc_type=doc_type.value,
        fields=fields,
        meta=meta,
    )
