from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:  # pragma: no cover - openai is an optional dependency at runtime
    AsyncOpenAI = None
    OpenAI = None

from app.core.config import get_settings
from app.core.enums import DocumentType
from app.core.schema import get_schema
from app.services import local_archive
from app.mock_services.hints import get_hints_text
from app.mock_services.templates import get_template_definition

settings = get_settings()
logger = logging.getLogger(__name__)

# HTTP remote filler API key (provider: http).
REMOTE_API_KEY = os.getenv("SUPPLYHUB_REMOTE_JSON_FILLER_API_KEY", "")
REMOTE_API_KEY_HEADER = os.getenv("SUPPLYHUB_REMOTE_JSON_FILLER_API_KEY_HEADER", "Authorization")
REMOTE_API_KEY_PREFIX = os.getenv("SUPPLYHUB_REMOTE_JSON_FILLER_API_KEY_PREFIX", "Bearer ")

# OpenRouter settings (provider: openrouter).
HARDCODED_OPENROUTER_API_KEY = os.getenv("HARDCODED_OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_MAIN = os.getenv("OPENROUTER_MODEL_MAIN", "openai/gpt-oss-120b")
OPENROUTER_MODEL_PRODUCTS = os.getenv("OPENROUTER_MODEL_PRODUCTS", OPENROUTER_MODEL_MAIN)
OPENROUTER_HTTP_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
OPENROUTER_X_TITLE = os.getenv("OPENROUTER_X_TITLE", "SupplyHub JSON Filler")

HINTS_EN_DIR = Path(__file__).resolve().parent.parent / "mock_services" / "hints_en"

MAX_LLM_RETRIES = int(os.getenv("JSON_FILLER_RETRIES", "3"))
MAX_TOKENS_JSON_CHARS = 200000
MAX_TEMPLATE_JSON_CHARS = 100000
MAX_TABLE_TOKENS_CHARS = 200000
MAX_CONTRACT_TOKENS_JSON_CHARS = 300000

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F]")
_LATIN_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")

PROMPT_MAIN = (
    "You convert OCR tokens into a structured JSON object of fields.\n\n"
    "Input:\n\n"
    "A JSON template (\"FIELDS TEMPLATE\") that defines all output fields.\n"
    "Each field is an object with:\n"
    "\"value\": string (initially \"\").\n"
    "\"token_refs\": array of token ids (initially []).\n\n"
    "Optional \"FIELD HINTS\" that describe how to extract each field.\n\n"
    "A list of OCR tokens (\"RAW TOKENS\"), each given as:\n"
    "token_id:\n"
    "token_text\n\n"
    "Your task:\n\n"
    "Use ONLY the RAW TOKENS to fill \"value\" and \"token_refs\" in the FIELDS TEMPLATE.\n"
    "When you set a non-empty \"value\", add in \"token_refs\" the first token ids whose text you used (even if there are multiple mentions).\n"
    "If you cannot confidently find a value, leave \"value\" as \"\" and \"token_refs\" as [].\n"
    "Copy text EXACTLY as it appears in the tokens (no corrections, no reformatting).\n"
    "Do NOT invent or guess values.\n"
    "The value can be, but is not guaranteed to be a FULL section. There can be multiple values in one section (one token id) "
    "or a value can be spread out between different sections. Your goal is to accurately fill the value, following the hints, "
    "and only then care about token_refs.\n"
    "Do NOT change the JSON structure: do not add, remove, or rename fields.\n"
    "Output MUST be a single valid JSON object with the same structure as the FIELDS TEMPLATE.\n"
    "Return ONLY the completed JSON, with no explanations or extra text.\n\n"
    "Critical rules (must follow):\n"
    "- Copy values EXACTLY from RAW TOKENS (same capitalization, punctuation, number/date formatting, and spacing). Do NOT normalize.\n"
    "- Do NOT add helper words (e.g., 'per', 'each', 'unit', currency) unless they appear in the source text.\n"
    "- If you found the value but cannot confidently pick token ids, still fill \"value\" and leave \"token_refs\" as [].\n"
)

PROMPT_PRODUCTS = (
    "You convert OCR tokens into structured JSON describing product rows.\n\n"
    "Input:\n\n"
    "A JSON template (\"PRODUCT TEMPLATE\") that lists every per-product field.\n"
    "Each field is an object with:\n"
    "\"value\": string (initially \"\").\n"
    "\"token_refs\": array of token ids (initially []).\n\n"
    "Optional \"FIELD HINTS\" that describe how to extract product-related data.\n\n"
    "A list of OCR tokens (\"RAW TOKENS\"), each given as:\n"
    "token_id:\n"
    "token_text\n\n"
    "Optional \"TABLE CANDIDATES\" block that contains raw HTML/delimited table tokens.\n\n"
    "Your task:\n\n"
    "Create product_1, product_2, ... for every real product row you find in the RAW TOKENS.\n"
    "For each product_N, copy the PRODUCT TEMPLATE exactly (same child fields) and fill only \"value\" and \"token_refs\".\n"
    "When you set a non-empty \"value\", add the token ids you used to \"token_refs\"; otherwise leave [].\n"
    "If a field is unknown, leave \"value\" as \"\".\n"
    "Copy text EXACTLY as it appears in the tokens/tables. Do NOT invent data.\n"
    "The value can be, but is not guaranteed to be a FULL section. There can be multiple values in one section (one token id) "
    "or a value can be spread out between different sections. Your goal is to accurately fill the value, following the hints, "
    "and only then care about token_refs.\n"
    "Output MUST be a single valid JSON object with one top-level key \"products\" containing product_1, product_2, ...\n"
    "Return ONLY the completed JSON, with no explanations or extra text.\n\n"
    "Critical rules (must follow):\n"
    "- Copy values EXACTLY from RAW TOKENS and/or TABLE CANDIDATES (same capitalization, punctuation, number/date formatting, and spacing). Do NOT normalize.\n"
    "- Do NOT add helper words (e.g., 'per', 'each', 'unit', currency) unless they appear in the source text.\n"
    "- If you found the value but cannot confidently pick token ids, still fill \"value\" and leave \"token_refs\" as [].\n\n"
    "Special note for products[*].unit_box:\n"
    "- unit_box is the literal unit string shown on the document (examples: 'ctn', 'bag', 'KG', 'USD / Kg', 'USD PER CARTON').\n"
    "- NEVER output 'per ...' unless the document literally contains 'per ...' for that unit.\n"
    "- Do NOT add extra punctuation like a leading '/' (e.g. '/ctn') unless it literally appears in the source.\n"
    "- Preserve the original casing exactly ('ctn' != 'CTN').\n"
)

_openrouter_client: Any | None = None
_openrouter_is_async = False
_openrouter_lock = asyncio.Lock()


def _build_headers() -> Dict[str, str]:
    if not REMOTE_API_KEY:
        return {}
    value = f"{REMOTE_API_KEY_PREFIX}{REMOTE_API_KEY}" if REMOTE_API_KEY_PREFIX else REMOTE_API_KEY
    return {REMOTE_API_KEY_HEADER: value}


def _openrouter_base_url() -> str:
    env = os.getenv("OPENROUTER_BASE_URL", "").strip()
    if env:
        return env
    if settings.remote_json_filler_endpoint:
        return str(settings.remote_json_filler_endpoint).rstrip("/")
    return "https://openrouter.ai/api/v1"


def _openrouter_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        key = os.getenv("SUPPLYHUB_OPENROUTER_API_KEY", "").strip()
    if not key:
        key = HARDCODED_OPENROUTER_API_KEY.strip()
    return key


async def _get_openrouter_client() -> Any | None:
    global _openrouter_client
    global _openrouter_is_async
    if _openrouter_client is not None:
        return _openrouter_client
    async with _openrouter_lock:
        if _openrouter_client is not None:
            return _openrouter_client
        api_key = _openrouter_api_key()
        if not api_key:
            return None
        headers = {
            "HTTP-Referer": OPENROUTER_HTTP_REFERER,
            "X-Title": OPENROUTER_X_TITLE,
        }
        base_url = _openrouter_base_url()
        if AsyncOpenAI is not None:
            _openrouter_client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                default_headers=headers,
            )
            _openrouter_is_async = True
        elif OpenAI is not None:
            _openrouter_client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                default_headers=headers,
            )
            _openrouter_is_async = False
        else:
            _openrouter_client = None
    return _openrouter_client


def _split_template_fields(fields: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    main_copy = deepcopy(fields or {})
    has_products = isinstance(fields, dict) and ("products" in fields)
    if has_products:
        main_copy.pop("products", None)
    return main_copy, has_products


def _is_leaf_field(value: Any) -> bool:
    return isinstance(value, dict) and "value" in value


def _prepare_prompt_template(node: Any) -> Any:
    if isinstance(node, dict):
        result: Dict[str, Any] = {}
        for key, value in node.items():
            if _is_leaf_field(value):
                result[key] = {
                    "value": value.get("value", ""),
                    "token_refs": value.get("token_refs", []),
                }
            else:
                result[key] = _prepare_prompt_template(value)
        return result
    if isinstance(node, list):
        return [_prepare_prompt_template(item) for item in node]
    return node


def _format_tokens_for_prompt(tokens: Any) -> str:
    if not isinstance(tokens, list):
        return str(tokens or "")
    lines: List[str] = []
    for idx, token in enumerate(tokens):
        if not isinstance(token, dict):
            continue
        token_id = token.get("id") or f"token_{idx}"
        text = token.get("text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)
        lines.append(f"{token_id}:")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def _format_table_candidates(tokens: List[Dict[str, Any]]) -> str:
    if not tokens:
        return ""
    lines: List[str] = []
    for idx, token in enumerate(tokens):
        if not isinstance(token, dict):
            continue
        token_id = token.get("id") or f"table_{idx}"
        text = token.get("text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)
        lines.append(f"{token_id}:")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def _format_dynamic_hint_lines(hints: Dict[str, List[str]]) -> List[str]:
    lines: List[str] = []
    if not isinstance(hints, dict):
        return lines
    for field, values in hints.items():
        if not values:
            continue
        for value in values:
            value_str = str(value).strip()
            if value_str:
                lines.append(f"{field}: {value_str}")
    return lines


def _compose_field_hints_block(curated_text: str, extra_lines: List[str]) -> str:
    parts: List[str] = []
    curated = (curated_text or "").strip()
    if curated:
        parts.append(curated)
    if extra_lines:
        parts.append("\n".join(extra_lines))
    return "\n".join(parts).strip()


def _collect_hints(doc_text: str) -> Dict[str, List[str]]:
    hints: Dict[str, List[str]] = {}

    inv_candidates = re.findall(r"(?:INVOICE[^0-9A-Za-z]{0,5})?No\.?|\\s*[:\\s-]*([A-Za-z0-9\\-_/]+)", doc_text, flags=re.I)
    if inv_candidates:
        hints["invoice_no"] = [c for c in inv_candidates if c]

    date_candidates = re.findall(
        r"\\b(?:\\d{1,2}[./-]\\d{1,2}[./-]\\d{2,4}|\\d{4}[./-]\\d{1,2}[./-]\\d{1,2}|"
        r"\\d{1,2}\\s+[A-Za-z]{3,12}\\s+\\d{4})\\b",
        doc_text,
        flags=re.I,
    )
    if date_candidates:
        hints["invoice_date"] = list(dict.fromkeys(date_candidates))

    inco_candidates = re.findall(r"\\b(INCOTERMS\\s*\\d{4})\\b", doc_text, flags=re.I)
    if inco_candidates:
        hints["incoterms"] = list(dict.fromkeys(inco_candidates))

    cont_candidates = re.findall(r"\\b(CONTAINER[:\\s-]*[A-Z0-9]+)\\b", doc_text, flags=re.I)
    if cont_candidates:
        hints["container"] = cont_candidates
    bl_candidates = re.findall(r"\\b(B/L\\s*NUMBER[:\\s-]*[A-Z0-9]+)\\b", doc_text, flags=re.I)
    if bl_candidates:
        hints["bl_number"] = bl_candidates

    buyer_candidates = re.findall(r"\\bBUYER/CONSIGNEE[:\\s-]+(.+)", doc_text, flags=re.I)
    if buyer_candidates:
        hints["buyer"] = buyer_candidates
    seller_candidates = re.findall(r"\\bSELLER/SHIPPER[:\\s-]+(.+)", doc_text, flags=re.I)
    if seller_candidates:
        hints["seller"] = seller_candidates

    return hints


def _find_table_like_tokens(tokens: Any) -> List[Dict[str, Any]]:
    if not isinstance(tokens, list):
        return []
    candidates: List[Dict[str, Any]] = []
    for token in tokens:
        try:
            text = token.get("text", "")
            if not isinstance(text, str):
                continue
            lowered = text.lower()
            if "<table" in lowered or "</tr>" in lowered or "</td>" in lowered:
                candidates.append(token)
                continue
            if text.count("|") >= 3:
                candidates.append(token)
                continue
        except Exception:
            continue
    return candidates


def _filter_contract_tokens(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _filter_cyrillic_tokens(tokens)


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


def _strip_specification_fields(node: Any) -> None:
    if isinstance(node, dict):
        if _is_leaf_field(node):
            value = node.get("value")
            if isinstance(value, str):
                cleaned = _strip_cyrillic_words(value)
                if cleaned != value:
                    node["value"] = cleaned
                    if not cleaned:
                        node["token_refs"] = []
            return
        for value in node.values():
            _strip_specification_fields(value)
    elif isinstance(node, list):
        for item in node:
            _strip_specification_fields(item)


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


def _filter_cyrillic_tokens(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
        if not _CYRILLIC_RE.search(text):
            filtered.append(token)
            continue
        cleaned = _CYRILLIC_RE.sub(" ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned or not _LATIN_OR_DIGIT_RE.search(cleaned):
            continue
        cleaned_token = dict(token)
        cleaned_token["text"] = cleaned
        filtered.append(cleaned_token)
    return filtered


def _filter_veterinary_certificate_tokens(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not tokens:
        return tokens
    return _filter_cyrillic_tokens(tokens)


def _token_limit_for_doc_type(doc_type: DocumentType) -> int:
    if doc_type == DocumentType.CONTRACT:
        return MAX_CONTRACT_TOKENS_JSON_CHARS
    return MAX_TOKENS_JSON_CHARS


def _split_curated_hints(hints_text: str) -> Tuple[str, str]:
    if not hints_text:
        return "", ""
    main_lines: List[str] = []
    product_lines: List[str] = []
    doc_type_lines: List[str] = []

    for raw_line in hints_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        prefix = line.split(":", 1)[0].strip().lower()
        if prefix == "doc_type":
            doc_type_lines.append(line)
            continue
        if prefix.startswith("products"):
            product_lines.append(line)
        else:
            main_lines.append(line)

    main_text_parts: List[str] = []
    if doc_type_lines:
        main_text_parts.extend(doc_type_lines)
    if main_lines:
        main_text_parts.extend(main_lines)

    product_text_parts: List[str] = []
    if doc_type_lines:
        product_text_parts.extend(doc_type_lines)
    if product_lines:
        product_text_parts.extend(product_lines)

    return "\n".join(main_text_parts), "\n".join(product_text_parts)


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


def _iter_json_fragments(text: str) -> Iterable[str]:
    if not text:
        return []
    in_string = False
    escape = False
    stack: List[str] = []
    start: Optional[int] = None
    pairs = {"{": "}", "[": "]"}

    for index, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in pairs:
            if not stack:
                start = index
            stack.append(ch)
            continue

        if ch in ("}", "]"):
            if not stack:
                continue
            opener = stack.pop()
            if pairs.get(opener) != ch:
                stack.clear()
                start = None
                continue
            if not stack and start is not None:
                yield text[start:index + 1]
                start = None


def _extract_json(payload: str) -> str:
    if not payload:
        return payload
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


def _sanitize_json_like(text: str, normalize_smart_quotes: bool = True) -> Tuple[str, bool]:
    if not text:
        return text, False
    original = text

    t = text
    if normalize_smart_quotes:
        t = (
            text.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
        )

    t = re.sub(r",\\s*([}\\]])", r"\\1", t)

    out: List[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(t):
        ch = t[i]
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                i += 1
                continue
            if ch == "\n":
                out.extend(["\\", "n"])
                i += 1
                continue
            if ch == "\r":
                out.extend(["\\", "n"])
                if i + 1 < len(t) and t[i + 1] == "\n":
                    i += 2
                else:
                    i += 1
                continue
            if ch == "\t":
                out.extend(["\\", "t"])
                i += 1
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        else:
            if ch == '"':
                in_string = True
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1

    changed = ("".join(out) != original)
    return "".join(out), changed


def _parse_json_str(raw: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    extracted = _extract_json(raw or "")
    try:
        data = json.loads(extracted)
        if isinstance(data, dict):
            return data, False
        return None, False
    except json.JSONDecodeError:
        pass

    sanitized, changed = _sanitize_json_like(extracted, normalize_smart_quotes=False)
    try:
        data = json.loads(sanitized)
        if isinstance(data, dict):
            return data, changed
        return None, changed
    except json.JSONDecodeError:
        pass

    sanitized, changed = _sanitize_json_like(extracted, normalize_smart_quotes=True)
    try:
        data = json.loads(sanitized)
        if isinstance(data, dict):
            return data, changed
        return None, changed
    except json.JSONDecodeError:
        repaired = re.sub(r",\\s*([}\\]])", r"\\1", sanitized)
        try:
            data = json.loads(repaired)
            if isinstance(data, dict):
                return data, True
        except Exception:
            return None, changed
    return None, changed


async def _openrouter_chat(messages: list, model: str, timeout: int) -> str:
    client = await _get_openrouter_client()
    if client is None:
        raise RuntimeError("OpenRouter client is not configured")
    if _openrouter_is_async:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            timeout=timeout,
        )
    else:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=messages,
            temperature=0,
            timeout=timeout,
        )
    return (resp.choices[0].message.content or "").strip()


async def _llm_json_with_retries(
    messages: list,
    model: str,
    timeout: int,
    *,
    doc_id: uuid.UUID | str | None = None,
    doc_type: DocumentType | None = None,
    file_name: Optional[str] = None,
    request_kind: str = "main",
) -> Optional[Dict[str, Any]]:
    last_raw: Optional[str] = None
    for attempt in range(1, max(1, MAX_LLM_RETRIES) + 1):
        try:
            msgs = deepcopy(messages)
            if attempt > 1:
                msgs.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous output was not valid JSON. Return strictly valid JSON only, "
                            "no markdown, no comments. Ensure all internal quotes are escaped."
                        ),
                    }
                )
            if local_archive.enabled() and doc_id is not None and doc_type is not None:
                local_archive.write_api_request(
                    doc_id=str(doc_id),
                    doc_type=doc_type,
                    request_kind=request_kind,
                    attempt=attempt,
                    payload={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "provider": "openrouter",
                        "request_kind": request_kind,
                        "attempt": attempt,
                        "doc_id": str(doc_id),
                        "doc_type": doc_type.value,
                        "file_name": file_name,
                        "model": model,
                        "temperature": 0,
                        "timeout": timeout,
                        "messages": msgs,
                    },
                )
            raw = await _openrouter_chat(msgs, model=model, timeout=timeout)
            last_raw = raw
            if local_archive.enabled() and doc_id is not None and doc_type is not None:
                local_archive.write_api_response(
                    doc_id=str(doc_id),
                    doc_type=doc_type,
                    request_kind=request_kind,
                    attempt=attempt,
                    payload={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "provider": "openrouter",
                        "request_kind": request_kind,
                        "attempt": attempt,
                        "doc_id": str(doc_id),
                        "doc_type": doc_type.value,
                        "file_name": file_name,
                        "model": model,
                        "raw_response": raw,
                    },
                )
            parsed, _ = _parse_json_str(raw)
            if parsed is not None:
                return parsed
        except Exception:
            logger.warning("OpenRouter attempt %d failed to parse JSON", attempt, exc_info=True)
            continue
    if last_raw:
        logger.warning("OpenRouter JSON parse failed; last_raw=%s", last_raw[:200])
    return None


def _build_messages_main(
    tokens: Any,
    fields_main_only: Dict[str, Any],
    hints: Dict[str, List[str]],
    curated_hints_text: Optional[str] = None,
    token_char_limit: int = MAX_TOKENS_JSON_CHARS,
) -> list:
    user_blocks: List[Dict[str, Any]] = []

    fields_template = _prepare_prompt_template(fields_main_only or {})
    fields_main_json = json.dumps(fields_template, ensure_ascii=False)
    if len(fields_main_json) > MAX_TEMPLATE_JSON_CHARS:
        fields_main_json = fields_main_json[:MAX_TEMPLATE_JSON_CHARS]
    user_blocks.append(
        {
            "type": "text",
            "text": f"=== FIELDS TEMPLATE ===\n{fields_main_json}\n=== END FIELDS TEMPLATE ===",
        }
    )

    dynamic_hint_lines = _format_dynamic_hint_lines(hints or {})
    hints_block = _compose_field_hints_block(curated_hints_text or "", dynamic_hint_lines)
    if hints_block:
        user_blocks.append(
            {
                "type": "text",
                "text": f"=== FIELD HINTS ===\n{hints_block}\n=== END FIELD HINTS ===",
            }
        )

    tokens_text = _format_tokens_for_prompt(tokens)
    if len(tokens_text) > token_char_limit:
        tokens_text = tokens_text[:token_char_limit]
    user_blocks.append(
        {
            "type": "text",
            "text": f"=== RAW TOKENS ===\n{tokens_text}\n=== END RAW TOKENS ===",
        }
    )

    messages = [
        {"role": "system", "content": PROMPT_MAIN},
        {"role": "user", "content": user_blocks},
    ]
    return messages


def _build_messages_products(
    tokens: Any,
    product_template: Dict[str, Any],
    table_like_tokens: List[Dict[str, Any]],
    curated_hints_text: Optional[str] = None,
    token_char_limit: int = MAX_TOKENS_JSON_CHARS,
) -> list:
    user_blocks: List[Dict[str, Any]] = []

    product_template_json = json.dumps(_prepare_prompt_template(product_template or {}), ensure_ascii=False)
    if len(product_template_json) > MAX_TEMPLATE_JSON_CHARS:
        product_template_json = product_template_json[:MAX_TEMPLATE_JSON_CHARS]
    user_blocks.append(
        {
            "type": "text",
            "text": f"=== PRODUCT TEMPLATE ===\n{product_template_json}\n=== END PRODUCT TEMPLATE ===",
        }
    )

    hints_block = _compose_field_hints_block(curated_hints_text or "", [])
    if hints_block:
        user_blocks.append(
            {
                "type": "text",
                "text": f"=== FIELD HINTS ===\n{hints_block}\n=== END FIELD HINTS ===",
            }
        )

    tokens_text = _format_tokens_for_prompt(tokens)
    if len(tokens_text) > token_char_limit:
        tokens_text = tokens_text[:token_char_limit]
    user_blocks.append(
        {
            "type": "text",
            "text": f"=== RAW TOKENS ===\n{tokens_text}\n=== END RAW TOKENS ===",
        }
    )

    table_text = _format_table_candidates(table_like_tokens)
    if table_text:
        if len(table_text) > MAX_TABLE_TOKENS_CHARS:
            table_text = table_text[:MAX_TABLE_TOKENS_CHARS]
        user_blocks.append(
            {
                "type": "text",
                "text": f"=== TABLE CANDIDATES ===\n{table_text}\n=== END TABLE CANDIDATES ===",
            }
        )

    messages = [
        {"role": "system", "content": PROMPT_PRODUCTS},
        {"role": "user", "content": user_blocks},
    ]
    return messages


def _ensure_leaf_arrays(node: Dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    for value in node.values():
        if _is_leaf_field(value):
            value.setdefault("bbox", [])
            value.setdefault("token_refs", [])
        elif isinstance(value, dict):
            _ensure_leaf_arrays(value)


def _merge_main_and_products(
    template_fields: Dict[str, Any],
    main_payload: Optional[Dict[str, Any]],
    products_payload: Optional[Dict[str, Any]],
    product_template: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    result = deepcopy(template_fields or {})

    if isinstance(main_payload, dict):
        fields_data = main_payload.get("fields") if "fields" in main_payload else main_payload
        if isinstance(fields_data, dict):
            for key, value in fields_data.items():
                if key == "products":
                    continue
                if key in result and isinstance(result[key], dict) and _is_leaf_field(result[key]) and isinstance(value, dict):
                    if "value" in value:
                        result[key]["value"] = value.get("value", result[key].get("value", ""))
                    if "bbox" in value:
                        result[key]["bbox"] = value.get("bbox", result[key].get("bbox", []))
                    if "token_refs" in value:
                        result[key]["token_refs"] = value.get("token_refs", result[key].get("token_refs", []))
                elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    for nk, nv in value.items():
                        if nk in result[key] and isinstance(result[key][nk], dict) and _is_leaf_field(result[key][nk]) and isinstance(nv, dict):
                            if "value" in nv:
                                result[key][nk]["value"] = nv.get("value", result[key][nk].get("value", ""))
                            if "bbox" in nv:
                                result[key][nk]["bbox"] = nv.get("bbox", result[key][nk].get("bbox", []))
                            if "token_refs" in nv:
                                result[key][nk]["token_refs"] = nv.get("token_refs", result[key][nk].get("token_refs", []))

    _ensure_leaf_arrays(result)

    if "products" in result and product_template is not None:
        if isinstance(products_payload, dict):
            prods = products_payload.get("products", products_payload)
            if isinstance(prods, dict) and prods:
                final_products: Dict[str, Any] = {}
                for pkey, pval in prods.items():
                    struct = deepcopy(product_template)
                    if isinstance(pval, dict):
                        for leaf_key in struct.keys():
                            if leaf_key in pval and isinstance(pval[leaf_key], dict):
                                cand = pval[leaf_key]
                                if "value" in cand:
                                    struct[leaf_key]["value"] = cand.get("value", "")
                                if "bbox" in cand:
                                    struct[leaf_key]["bbox"] = cand.get("bbox", [])
                                if "token_refs" in cand:
                                    struct[leaf_key]["token_refs"] = cand.get("token_refs", [])
                    _ensure_leaf_arrays(struct)
                    final_products[pkey] = struct
                result["products"] = final_products
            else:
                result["products"] = result.get("products", {})

    _ensure_leaf_arrays(result)
    return result


async def _fill_json_http(
    doc_id: uuid.UUID,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str] = None,
    ocr_tokens: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    endpoint = settings.remote_json_filler_endpoint
    if not endpoint:
        logger.warning("Remote JSON filler endpoint not configured; returning stub for %s", doc_id)
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

    timeout = float(settings.remote_json_filler_timeout)
    headers = _build_headers()

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(str(endpoint), json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            logger.warning(
                "Remote JSON filler failed; returning stub for %s",
                doc_id,
                exc_info=True,
            )
            return _stub_fill_json(doc_id, doc_type, doc_text)


async def _fill_json_openrouter(
    doc_id: uuid.UUID,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str] = None,
    ocr_tokens: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not _openrouter_api_key():
        logger.warning("OpenRouter API key not configured; returning stub for %s", doc_id)
        return _stub_fill_json(doc_id, doc_type, doc_text)
    if AsyncOpenAI is None and OpenAI is None:
        logger.warning("openai package not available; returning stub for %s", doc_id)
        return _stub_fill_json(doc_id, doc_type, doc_text)

    template_def = get_template_definition(doc_type)
    full_template_fields: Dict[str, Any] = deepcopy(template_def.get("fields", {}))
    product_template: Optional[Dict[str, Any]] = template_def.get("product_template")

    fields_main_only, has_products = _split_template_fields(full_template_fields)

    hints = _collect_hints(doc_text or "")
    curated_hints_text = get_hints_text(doc_type, base_dir=HINTS_EN_DIR) or get_hints_text(doc_type)
    main_hints_text, product_hints_text = _split_curated_hints(curated_hints_text)

    tokens_list: List[Dict[str, Any]] = []
    if isinstance(ocr_tokens, list):
        tokens_list = list(ocr_tokens)
    elif ocr_tokens is not None:
        tokens_list = list(ocr_tokens)
    if not tokens_list and doc_text:
        tokens_list = [{"id": "plain_text", "text": doc_text}]

    timeout = int(settings.remote_json_filler_timeout)
    if doc_type == DocumentType.CONTRACT:
        prompt_tokens = _filter_contract_tokens(tokens_list)
    elif doc_type == DocumentType.VETERINARY_CERTIFICATE:
        prompt_tokens = _filter_veterinary_certificate_tokens(tokens_list)
    elif doc_type == DocumentType.SPECIFICATION:
        prompt_tokens = _filter_specification_tokens(tokens_list)
    else:
        prompt_tokens = tokens_list

    token_limit = _token_limit_for_doc_type(doc_type)
    msgs_main = _build_messages_main(
        tokens=prompt_tokens,
        fields_main_only=fields_main_only,
        hints=hints,
        curated_hints_text=main_hints_text,
        token_char_limit=token_limit,
    )
    main_payload = await _llm_json_with_retries(
        msgs_main,
        model=OPENROUTER_MODEL_MAIN,
        timeout=timeout,
        doc_id=doc_id,
        doc_type=doc_type,
        file_name=file_name,
        request_kind="main",
    )

    products_payload: Optional[Dict[str, Any]] = None
    if has_products and product_template is not None:
        table_like = _find_table_like_tokens(prompt_tokens)
        products_tokens = prompt_tokens
        if table_like:
            products_tokens = []
        msgs_products = _build_messages_products(
            tokens=products_tokens,
            product_template=product_template,
            table_like_tokens=table_like,
            curated_hints_text=product_hints_text,
            token_char_limit=token_limit,
        )
        products_payload = await _llm_json_with_retries(
            msgs_products,
            model=OPENROUTER_MODEL_PRODUCTS,
            timeout=timeout,
            doc_id=doc_id,
            doc_type=doc_type,
            file_name=file_name,
            request_kind="products",
        )

    merged_fields = _merge_main_and_products(
        template_fields=full_template_fields,
        main_payload=main_payload,
        products_payload=products_payload,
        product_template=product_template,
    )

    return {
        "doc_id": str(doc_id),
        "doc_type": doc_type.value,
        "fields": merged_fields,
        "meta": {"source": "openrouter"},
    }


async def fill_json(
    doc_id: uuid.UUID,
    doc_type: DocumentType,
    doc_text: str,
    file_name: Optional[str] = None,
    ocr_tokens: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    provider = (settings.remote_json_filler_provider or "http").strip().lower()
    if provider == "openrouter":
        result = await _fill_json_openrouter(
            doc_id,
            doc_type,
            doc_text=doc_text,
            file_name=file_name,
            ocr_tokens=ocr_tokens,
        )
    else:
        result = await _fill_json_http(
            doc_id,
            doc_type,
            doc_text=doc_text,
            file_name=file_name,
            ocr_tokens=ocr_tokens,
        )
    if doc_type == DocumentType.SPECIFICATION:
        fields = result.get("fields")
        if fields is not None:
            _strip_specification_fields(fields)
    return result


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
        "meta": {"stub": True, "remote": True},
    }
