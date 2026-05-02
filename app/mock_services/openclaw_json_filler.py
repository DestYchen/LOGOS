from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from typing import Any, Dict, Iterator, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.enums import DocumentType
from app.mock_services.templates import get_template_definition


logger = logging.getLogger(__name__)

OPENCLAW_FILLER_BASE_URL = os.getenv("OPENCLAW_FILLER_BASE_URL", "http://127.0.0.1:18789/v1/responses")
OPENCLAW_FILLER_MODEL = os.getenv("OPENCLAW_FILLER_MODEL", os.getenv("OPENCLAW_MODEL", "openclaw/default"))
OPENCLAW_API_TOKEN = os.getenv("OPENCLAW_API_TOKEN", "")
OPENCLAW_FILLER_TIMEOUT = float(os.getenv("OPENCLAW_FILLER_TIMEOUT", os.getenv("OPENCLAW_TIMEOUT", "180")))
OPENCLAW_FILLER_MAX_TOKENS_CHARS = int(os.getenv("OPENCLAW_FILLER_MAX_TOKENS_CHARS", "200000"))
OPENCLAW_FILLER_MAX_TEXT_CHARS = int(os.getenv("OPENCLAW_FILLER_MAX_TEXT_CHARS", "40000"))
OPENCLAW_FILLER_MAX_TEMPLATE_CHARS = int(os.getenv("OPENCLAW_FILLER_MAX_TEMPLATE_CHARS", "100000"))


class FillerRequest(BaseModel):
    doc_id: str
    doc_type: DocumentType
    doc_text: str
    file_name: Optional[str] = None
    tokens: Optional[Any] = None


class FillerResponse(BaseModel):
    doc_id: str
    doc_type: str
    fields: Dict[str, Any]
    meta: Dict[str, Any]


app = FastAPI(title="OpenClaw JSON Filler Adapter")


@app.post("/v1/fill", response_model=FillerResponse)
async def fill(request: FillerRequest) -> FillerResponse:
    template_def = get_template_definition(request.doc_type)
    template_fields = deepcopy(template_def.get("fields", {}))
    product_template = deepcopy(template_def.get("product_template"))

    prompt = _build_prompt(
        doc_type=request.doc_type,
        file_name=request.file_name,
        doc_text=request.doc_text or "",
        tokens=request.tokens,
        template_fields=template_fields,
        product_template=product_template,
    )

    logger.info(
        "openclaw_json_filler request doc_id=%s type=%s file=%s text_len=%s",
        request.doc_id,
        request.doc_type.value,
        request.file_name or "",
        len(request.doc_text or ""),
    )

    raw = await _call_openclaw(prompt)
    payload, repaired = _parse_json_payload(raw)
    fields = _merge_payload_into_template(template_fields, payload, product_template)
    meta = {
        "provider": "openclaw",
        "model": OPENCLAW_FILLER_MODEL,
        "repaired": repaired,
        "raw_empty": not bool((raw or "").strip()),
        "parsed": isinstance(payload, dict),
    }
    return FillerResponse(doc_id=request.doc_id, doc_type=request.doc_type.value, fields=fields, meta=meta)


def _build_prompt(
    *,
    doc_type: DocumentType,
    file_name: Optional[str],
    doc_text: str,
    tokens: Any,
    template_fields: Dict[str, Any],
    product_template: Optional[Dict[str, Any]] = None,
) -> str:
    prompt_template = _prepare_prompt_template(template_fields)
    template_json = json.dumps(prompt_template, ensure_ascii=False)
    if len(template_json) > OPENCLAW_FILLER_MAX_TEMPLATE_CHARS:
        template_json = template_json[:OPENCLAW_FILLER_MAX_TEMPLATE_CHARS]

    product_template_json = ""
    if isinstance(product_template, dict) and product_template:
        product_prompt_template = _prepare_prompt_template(product_template)
        product_template_json = json.dumps(product_prompt_template, ensure_ascii=False)
        if len(product_template_json) > OPENCLAW_FILLER_MAX_TEMPLATE_CHARS:
            product_template_json = product_template_json[:OPENCLAW_FILLER_MAX_TEMPLATE_CHARS]

    token_text = _format_tokens_for_prompt(tokens)
    if len(token_text) > OPENCLAW_FILLER_MAX_TOKENS_CHARS:
        token_text = token_text[:OPENCLAW_FILLER_MAX_TOKENS_CHARS]

    if OPENCLAW_FILLER_MAX_TEXT_CHARS and len(doc_text) > OPENCLAW_FILLER_MAX_TEXT_CHARS:
        doc_text = doc_text[:OPENCLAW_FILLER_MAX_TEXT_CHARS]

    products_instruction = ""
    if product_template_json:
        products_instruction = (
            "The field named products is expandable. If the document contains product, goods, cargo, "
            "or line-item rows, create products.product_1, products.product_2, etc. in source order. "
            "Each product_N must copy PRODUCT TEMPLATE exactly and fill only value and token_refs. "
            "Leave missing product field values empty. If no real product rows exist, return products as {}.\n\n"
            f"PRODUCT TEMPLATE:\n{product_template_json}\n\n"
        )

    return (
        "You fill structured JSON fields for logistics and foreign-trade documents.\n"
        "Return only a valid JSON object. No prose, markdown, or comments.\n"
        "Use only the provided OCR tokens and document text. Do not invent values.\n"
        "Preserve the exact template structure and field names.\n"
        "For each leaf field, fill only value and token_refs. Leave unknown values empty.\n"
        "If you cannot identify token ids confidently, fill value and leave token_refs as [].\n\n"
        "Product-row rules:\n"
        "- A product row may be written in a table, a paragraph, or a numbered goods list.\n"
        "- Copy values exactly as written in OCR text; do not normalize units, prices, weights, dates, or names.\n"
        "- Put repeated products under products.product_1, products.product_2, ...; do not invent extra rows.\n\n"
        f"DOCUMENT TYPE:\n{doc_type.value}\n\n"
        f"FILE NAME:\n{file_name or ''}\n\n"
        f"FIELDS TEMPLATE:\n{template_json}\n\n"
        f"{products_instruction}"
        f"OCR TOKENS:\n{token_text}\n\n"
        f"DOCUMENT TEXT:\n{doc_text}\n"
    )


async def _call_openclaw(prompt: str) -> str:
    if not OPENCLAW_API_TOKEN:
        raise HTTPException(status_code=500, detail="openclaw_api_token_not_configured")

    payload = {
        "model": OPENCLAW_FILLER_MODEL,
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
        async with httpx.AsyncClient(timeout=OPENCLAW_FILLER_TIMEOUT) as client:
            response = await client.post(OPENCLAW_FILLER_BASE_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"openclaw_request_failed:{exc}") from exc

    if response.status_code >= 400:
        logger.warning("OpenClaw filler failed status=%s body=%s", response.status_code, response.text[:1000])
        raise HTTPException(status_code=502, detail="openclaw_request_failed")

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="openclaw_invalid_json") from exc

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
    if isinstance(output_text, str):
        return output_text

    return ""


def _parse_json_payload(raw: str) -> Tuple[Dict[str, Any], bool]:
    if not raw:
        return {}, False
    extracted = _extract_json(raw)
    for candidate, repaired in (
        (extracted, False),
        (_sanitize_json_like(extracted, normalize_smart_quotes=False), True),
        (_sanitize_json_like(extracted, normalize_smart_quotes=True), True),
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
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in pairs:
            if not stack:
                start = index
            stack.append(char)
            continue
        if char in ("}", "]") and stack:
            opener = stack.pop()
            if pairs.get(opener) != char:
                stack.clear()
                start = None
                continue
            if not stack and start is not None:
                yield text[start:index + 1]
                start = None


def _sanitize_json_like(text: str, *, normalize_smart_quotes: bool) -> str:
    if not text:
        return text
    if normalize_smart_quotes:
        text = (
            text.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
        )
    text = re.sub(r",\s*([}\]])", r"\1", text)
    out: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if in_string:
            if escape:
                out.append(char)
                escape = False
                continue
            if char == "\\":
                out.append(char)
                escape = True
                continue
            if char == "\n":
                out.extend(["\\", "n"])
                continue
            if char == "\r":
                out.extend(["\\", "n"])
                continue
            if char == "\t":
                out.extend(["\\", "t"])
                continue
            if char == '"':
                in_string = False
            out.append(char)
            continue
        if char == '"':
            in_string = True
        out.append(char)
    return "".join(out)


def _merge_payload_into_template(
    template_fields: Dict[str, Any],
    payload: Dict[str, Any],
    product_template: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    result = deepcopy(template_fields or {})
    fields_data = payload.get("fields") if isinstance(payload, dict) and isinstance(payload.get("fields"), dict) else payload
    if isinstance(fields_data, dict):
        _merge_node(result, fields_data)
        _merge_products(result, fields_data.get("products"), product_template)
    _ensure_leaf_defaults(result)
    return result


def _merge_node(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for key, source_value in source.items():
        if key == "products":
            continue
        if key not in target or not isinstance(source_value, dict) or not isinstance(target.get(key), dict):
            continue
        target_value = target[key]
        if _is_leaf_field(target_value):
            _apply_leaf_update(target_value, source_value)
        else:
            _merge_node(target_value, source_value)


def _merge_products(target: Dict[str, Any], products_payload: Any, product_template: Optional[Dict[str, Any]]) -> None:
    if "products" not in target or not isinstance(products_payload, dict) or not isinstance(product_template, dict):
        return
    merged: Dict[str, Any] = {}
    for product_key, product_payload in products_payload.items():
        if not isinstance(product_payload, dict):
            continue
        product_result = deepcopy(product_template)
        _merge_node(product_result, product_payload)
        _ensure_leaf_defaults(product_result)
        merged[str(product_key)] = product_result
    if merged:
        target["products"] = merged


def _apply_leaf_update(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    if "value" in source:
        value = source.get("value")
        target["value"] = "" if value is None else str(value)
    if isinstance(source.get("token_refs"), list):
        target["token_refs"] = source.get("token_refs", [])
    if isinstance(source.get("bbox"), list):
        target["bbox"] = source.get("bbox", [])
    if source.get("page") is not None:
        target["page"] = source.get("page")
    if source.get("source"):
        target["source"] = source.get("source")


def _ensure_leaf_defaults(node: Any) -> None:
    if isinstance(node, dict):
        if _is_leaf_field(node):
            node.setdefault("value", "")
            node.setdefault("token_refs", [])
            node.setdefault("bbox", [])
            node.setdefault("page", None)
            node.setdefault("source", "llm")
            return
        for value in node.values():
            _ensure_leaf_defaults(value)
    elif isinstance(node, list):
        for value in node:
            _ensure_leaf_defaults(value)


def _prepare_prompt_template(node: Any) -> Any:
    if isinstance(node, dict):
        result: Dict[str, Any] = {}
        for key, value in node.items():
            if _is_leaf_field(value):
                result[key] = {"value": value.get("value", ""), "token_refs": value.get("token_refs", [])}
            else:
                result[key] = _prepare_prompt_template(value)
        return result
    if isinstance(node, list):
        return [_prepare_prompt_template(item) for item in node]
    return node


def _format_tokens_for_prompt(tokens: Any) -> str:
    if not isinstance(tokens, list):
        return str(tokens or "")
    lines: list[str] = []
    for index, token in enumerate(tokens):
        if not isinstance(token, dict):
            continue
        token_id = token.get("id") or f"token_{index}"
        text = token.get("text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)
        lines.append(f"{token_id}:")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def _is_leaf_field(value: Any) -> bool:
    return isinstance(value, dict) and "value" in value
