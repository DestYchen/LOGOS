from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.enums import DocumentType


logger = logging.getLogger(__name__)

OPENCLAW_ASSEMBLER_BASE_URL = os.getenv("OPENCLAW_ASSEMBLER_BASE_URL", "http://127.0.0.1:18789/v1/responses")
OPENCLAW_ASSEMBLER_MODEL = os.getenv("OPENCLAW_ASSEMBLER_MODEL", os.getenv("OPENCLAW_MODEL", "openclaw/default"))
OPENCLAW_API_TOKEN = os.getenv("OPENCLAW_API_TOKEN", "")
OPENCLAW_ASSEMBLER_TIMEOUT = float(os.getenv("OPENCLAW_ASSEMBLER_TIMEOUT", os.getenv("OPENCLAW_TIMEOUT", "120")))
OPENCLAW_ASSEMBLER_MAX_PAGE_CHARS = int(os.getenv("OPENCLAW_ASSEMBLER_MAX_PAGE_CHARS", "5000"))

STRONG_TITLES = {
    "CERTIFICATE OF ORIGIN",
    "QUALITY CERTIFICATE",
    "PACKING LIST",
    "BILL OF LADING",
    "VETERINARY CERTIFICATE",
    "HEALTH CERTIFICATE",
    "SPECIFICATION",
    "COMMERCIAL INVOICE",
    "PROFORMA INVOICE",
    "INVOICE",
    "CMR",
    "T1",
}


class AssemblyPage(BaseModel):
    doc_id: str
    filename: str
    source_group: str
    page_index: int = Field(default=1, ge=1)
    doc_type: str
    doc_text: str = ""
    tokens: Optional[List[Dict[str, Any]]] = None


class AssemblyRequest(BaseModel):
    batch_id: str
    pages: List[AssemblyPage]


class AssemblyGroup(BaseModel):
    group_id: str
    final_doc_type: str
    page_doc_ids: List[str]
    confidence: float = 1.0
    reason: str = ""


class AssemblyResponse(BaseModel):
    groups: List[AssemblyGroup]


app = FastAPI(title="OpenClaw Document Assembler")


@app.post("/v1/assemble", response_model=AssemblyResponse)
async def assemble(request: AssemblyRequest) -> AssemblyResponse:
    groups: List[AssemblyGroup] = []
    pages_by_source: Dict[str, List[AssemblyPage]] = defaultdict(list)
    for page in request.pages:
        pages_by_source[page.source_group].append(page)

    group_counter = 1
    for source_group in sorted(pages_by_source):
        source_pages = sorted(pages_by_source[source_group], key=lambda item: (item.page_index, item.filename))
        source_groups = await _assemble_source_pages(source_group, source_pages)
        for group in source_groups:
            group.group_id = f"group_{group_counter}"
            groups.append(group)
            group_counter += 1

    return AssemblyResponse(groups=groups)


async def _assemble_source_pages(source_group: str, pages: List[AssemblyPage]) -> List[AssemblyGroup]:
    if not pages:
        return []
    if len(pages) == 1:
        return [_single_page_group(pages[0], "single page")]

    raw = await _call_openclaw(_build_prompt(source_group, pages))
    payload, parsed = _parse_json_payload(raw)
    if parsed:
        groups = _normalize_groups(payload, pages)
        if groups:
            return groups

    logger.warning("Assembler falling back to conservative no-op groups for %s", source_group)
    return [_single_page_group(page, "assembler fallback") for page in pages]


def _single_page_group(page: AssemblyPage, reason: str) -> AssemblyGroup:
    return AssemblyGroup(
        group_id="",
        final_doc_type=_normalize_doc_type(page.doc_type),
        page_doc_ids=[page.doc_id],
        confidence=1.0,
        reason=reason,
    )


def _build_prompt(source_group: str, pages: List[AssemblyPage]) -> str:
    allowed_types = ", ".join(doc_type.value for doc_type in DocumentType)
    page_blocks = []
    for page in pages:
        text = (page.doc_text or "").strip()
        if len(text) > OPENCLAW_ASSEMBLER_MAX_PAGE_CHARS:
            text = text[:OPENCLAW_ASSEMBLER_MAX_PAGE_CHARS]
        page_blocks.append(
            "\n".join(
                [
                    f"doc_id: {page.doc_id}",
                    f"filename: {page.filename}",
                    f"page_index: {page.page_index}",
                    f"classifier_doc_type: {page.doc_type}",
                    "text:",
                    text,
                ]
            )
        )
    return (
        "You assemble split PDF pages into logical trade documents.\n"
        "Pages are from one original source file only. Keep page order.\n"
        "Return strict JSON only with this shape:\n"
        '{"groups":[{"final_doc_type":"INVOICE","page_doc_ids":["doc1","doc2"],"confidence":0.8,"reason":"short reason"}]}\n'
        "Rules:\n"
        "- Merge only consecutive pages that continue the same logical document.\n"
        "- Do not merge if a page clearly starts a new document with a strong title/header.\n"
        "- A classifier label can be wrong on continuation pages; use text context and page order.\n"
        "- Use only allowed final_doc_type values.\n"
        "- Every input doc_id must appear exactly once.\n"
        f"Allowed types: {allowed_types}\n"
        f"Source group: {source_group}\n\n"
        "PAGES:\n"
        + "\n\n--- PAGE ---\n\n".join(page_blocks)
    )


async def _call_openclaw(prompt: str) -> str:
    if not OPENCLAW_API_TOKEN:
        return ""

    payload = {
        "model": OPENCLAW_ASSEMBLER_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENCLAW_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=OPENCLAW_ASSEMBLER_TIMEOUT) as client:
            response = await client.post(OPENCLAW_ASSEMBLER_BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.warning("OpenClaw assembler request failed", exc_info=True)
        return ""
    return _extract_response_text(data)


def _extract_response_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(str(content.get("text", "")))
    if chunks:
        return "\n".join(part for part in chunks if part)
    output_text = data.get("output_text")
    return output_text if isinstance(output_text, str) else ""


def _parse_json_payload(raw: str) -> Tuple[Dict[str, Any], bool]:
    if not raw:
        return {}, False
    extracted = _extract_json(raw)
    for candidate in (extracted, _sanitize_json_like(extracted)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return (data if isinstance(data, dict) else {}, True)
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
            return candidate
        except Exception:
            continue
    return cleaned


def _strip_markdown_fence(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _iter_json_fragments(text: str) -> Iterator[str]:
    in_string = False
    escape = False
    stack: list[str] = []
    start: Optional[int] = None
    pairs = {"{": "}", "[": "]"}
    for index, char in enumerate(text or ""):
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
            continue
        if char in pairs:
            if not stack:
                start = index
            stack.append(char)
        elif char in ("}", "]") and stack:
            opener = stack.pop()
            if pairs.get(opener) != char:
                stack.clear()
                start = None
            elif not stack and start is not None:
                yield text[start:index + 1]
                start = None


def _sanitize_json_like(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text or "")


def _normalize_groups(payload: Dict[str, Any], pages: List[AssemblyPage]) -> List[AssemblyGroup]:
    raw_groups = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(raw_groups, list):
        return []

    pages_by_id = {page.doc_id: page for page in pages}
    page_order = {page.doc_id: index for index, page in enumerate(pages)}
    seen: set[str] = set()
    groups: List[AssemblyGroup] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            continue
        raw_doc_ids = raw_group.get("page_doc_ids")
        if not isinstance(raw_doc_ids, list):
            continue
        doc_ids = [str(doc_id) for doc_id in raw_doc_ids if str(doc_id) in pages_by_id and str(doc_id) not in seen]
        doc_ids.sort(key=lambda doc_id: page_order[doc_id])
        if not doc_ids or not _is_consecutive(doc_ids, page_order):
            continue
        for doc_id in doc_ids:
            seen.add(doc_id)
        final_doc_type = _normalize_doc_type(str(raw_group.get("final_doc_type") or pages_by_id[doc_ids[0]].doc_type))
        groups.append(
            AssemblyGroup(
                group_id="",
                final_doc_type=final_doc_type,
                page_doc_ids=doc_ids,
                confidence=_normalize_confidence(raw_group.get("confidence")),
                reason=str(raw_group.get("reason") or ""),
            )
        )

    for page in pages:
        if page.doc_id not in seen:
            groups.append(_single_page_group(page, "missing from assembler output"))
    groups.sort(key=lambda group: page_order[group.page_doc_ids[0]])
    return groups


def _is_consecutive(doc_ids: List[str], page_order: Dict[str, int]) -> bool:
    indexes = [page_order[doc_id] for doc_id in doc_ids]
    return indexes == list(range(indexes[0], indexes[0] + len(indexes)))


def _normalize_doc_type(raw: str) -> str:
    token = (raw or "").strip().split()[0].strip("`\"' ")
    token_upper = token.upper().replace("-", "_")
    for doc_type in DocumentType:
        if token_upper in {doc_type.value.upper().replace("-", "_"), doc_type.name.upper()}:
            return doc_type.value
    return DocumentType.UNKNOWN.value


def _normalize_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return min(max(value, 0.0), 1.0)
