from __future__ import annotations

import json
import os
import logging
import re
from copy import deepcopy
from typing import Any, Dict, Iterator, Optional, Tuple, List
from urllib import request as urlrequest

from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel
from app.core.enums import DocumentType
from app.mock_services.templates import get_template_definition
from app.mock_services.hints import get_hints_text
from pathlib import Path


# =========================
# Top-level configuration
# =========================

# Base URL and API key: left empty by default; your teammate can run via OpenRouter by setting env vars.
# - OPENAI_BASE_URL (e.g., "https://openrouter.ai/api/v1" or your local http://host:port/v1)
# - OPENAI_API_KEY (e.g., OpenRouter key). If empty, the client is still created; your local server may not require it.
LLM_BASE_URL: str = "http://10.0.0.247:1234/v1"
LLM_API_KEY: str = ""  # intentionally left empty by default

# Model names (can be the same or different; overridable via env)
LLM_MODEL_MAIN: str = "openai/gpt-oss-20b"
LLM_MODEL_PRODUCTS: str = LLM_MODEL_MAIN

# Reasoning effort (used for responses API). Default to low for speed.
LLM_REASONING_EFFORT: str = os.getenv("JSON_FILLER_REASONING_EFFORT", "low")

# English hints directory (scaffold 14).
HINTS_EN_DIR: Path = Path(__file__).resolve().parent / "hints_en"

# System prompts tuned to the new token-only format.
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
    "The value can be, but is not guaranteed to be a FULL section. There can be multiple values in one section (one token id) or a value can be spread out between different sections. Basically your goal is to accurately fill the value, following the hints, and only then you should start to care about token_refs, to find the one that best corresponds to this value.\n"
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
    "The value can be, but is not guaranteed to be a FULL section. There can be multiple values in one section (one token id) or a value can be spread out between different sections. Basically your goal is to accurately fill the value, following the hints, and only then you should start to care about token_refs, to find the one that best corresponds to this value.\n"
    "Output MUST be a single valid JSON object with one top-level key \"products\" containing product_1, product_2, ...\n"
    "Return ONLY the completed JSON, with no explanations or extra text.\n\n"
    "Critical rules (must follow):\n"
    "- Copy values EXACTLY from RAW TOKENS and/or TABLE CANDIDATES (same capitalization, punctuation, number/date formatting, and spacing). Do NOT normalize.\n"
    "- Do NOT add helper words (e.g., 'per', 'each', 'unit', currency) unless they appear in the source text. Hints may contain normalized examples; ignore those if they don't literally occur.\n"
    "- If you found the value but cannot confidently pick token ids, still fill \"value\" and leave \"token_refs\" as [].\n\n"
    "Special note for products[*].unit_box:\n"
    "- unit_box is the literal unit string shown on the document (examples: 'ctn', 'bag', 'KG', 'USD / Kg', 'USD PER CARTON').\n"
    "- NEVER output 'per ...' unless the document literally contains 'per ...' for that unit.\n"
    "- Do NOT add extra punctuation like a leading '/' (e.g. '/ctn') unless it literally appears in the source.\n"
    "- Preserve the original casing exactly ('ctn' != 'CTN').\n"
)


# =========================
# Logging setup
# =========================

logger = logging.getLogger(__name__)
# Allow runtime control of verbosity
_LOG_LEVEL = os.getenv("JSON_FILLER_LOG_LEVEL", "INFO").upper()
_DETAILED = os.getenv("JSON_FILLER_DETAILED", "0") in ("1", "true", "True", "yes", "on")
try:
    logger.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
except Exception:
    logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [json_filler] %(message)s"))
    logger.addHandler(_handler)


def _brief(s: str, limit: int = 300) -> str:
    if not s:
        return ""
    s = (s or "").strip().replace("\n", " ")
    return (s[:limit] + "…") if len(s) > limit else s


def _brief_json(obj: Any, limit: int = 1200) -> str:
    try:
        dumped = json.dumps(obj, ensure_ascii=False)
    except Exception:
        dumped = str(obj)
    return dumped if len(dumped) <= limit else (dumped[:limit] + "…")


# Retry configuration
MAX_LLM_RETRIES: int = int(os.getenv("JSON_FILLER_RETRIES", "3"))

# Hard caps to avoid overflowing small-context models (e.g., 4k tokens).
# Use conservative character limits to leave space for system prompts
# and model overhead.
MAX_TOKENS_JSON_CHARS = 200000
MAX_TEMPLATE_JSON_CHARS = 100000
MAX_TABLE_TOKENS_CHARS = 200000
MAX_HINTS_TEXT_CHARS = 40000


# =========================
# Request/Response models
# =========================

class FillerRequest(BaseModel):
    doc_id: str
    doc_type: DocumentType
    doc_text: str
    file_name: Optional[str] = None
    tokens: Optional[Any] = None  # typically a list[dict]


class FillerResponse(BaseModel):
    doc_id: str
    fields: Dict[str, Dict[str, Any]]
    meta: Dict[str, Any]


# =========================
# FastAPI app and client
# =========================

app = FastAPI(title="ChatGPT JSON Filler Adapter (Split Main/Products)")


def _create_client() -> OpenAI:
    """
    Build a generic OpenAI-compatible client pointing at LLM_BASE_URL.
    API key may be empty (local gateways often don't check).
    """
    headers = {}
    # OpenRouter-style optional headers (harmless if unused):
    # note: not required, but sometimes helpful in shared infra.
    headers["HTTP-Referer"] = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
    headers["X-Title"] = os.getenv("OPENROUTER_X_TITLE", "OCR JSON Filler")

    return OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        default_headers=headers or None,
    )


client: Optional[OpenAI] = None
_PROMPT_DUMP_DIR: Optional[Path] = None


@app.on_event("startup")
def init_client() -> None:
    global client
    global _PROMPT_DUMP_DIR
    if client is None:
        client = _create_client()
        logger.info("LLM client initialized (base_url=%s, model_main=%s, model_products=%s)",
                    LLM_BASE_URL, LLM_MODEL_MAIN, LLM_MODEL_PRODUCTS)
    # Ensure prompt dump directory exists at app/mock_services/prompts
    try:
        dump_dir = Path(__file__).resolve().parent / "prompts"
        dump_dir.mkdir(parents=True, exist_ok=True)
        _PROMPT_DUMP_DIR = dump_dir
        logger.info("Prompt dump dir: %s", dump_dir)
    except Exception:
        logger.warning("Failed to prepare prompt dump directory", exc_info=True)


# =========================
# JSON salvage utilities
# =========================

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


def _supports_responses_reasoning(model: str) -> bool:
    return (model or "").startswith("openai/gpt-oss")


def _content_part_to_text(part: Any) -> str:
    if isinstance(part, dict):
        if part.get("type") == "text":
            return str(part.get("text") or "")
        if part.get("type") == "image_url":
            return str(part.get("image_url") or "")
        return str(part)
    return str(part)


def _messages_to_input_text(messages: list) -> str:
    chunks: List[str] = []
    for msg in messages:
        role = str(msg.get("role") or "").upper()
        content = msg.get("content")
        if isinstance(content, list):
            text = "\n".join(_content_part_to_text(p) for p in content if p is not None)
        else:
            text = str(content or "")
        chunks.append(f"{role}:\n{text}")
    return "\n\n".join(chunks).strip()


def _extract_responses_text(data: Any) -> str:
    if isinstance(data, dict):
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text.strip()
        output = data.get("output")
        if isinstance(output, list) and output:
            # First, prefer assistant message output_text blocks.
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if not isinstance(text, str) or not text.strip():
                        continue
                    if part.get("type") in ("output_text", "text"):
                        return text.strip()
            # Fallback: any non-reasoning text block.
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "reasoning_text":
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
    return ""


def _is_json_fragment(fragment: str) -> bool:
    if not fragment:
        return False
    try:
        json.loads(fragment)
    except Exception:
        return False
    return True


def _iter_json_fragments(text: str) -> Iterator[str]:
    if not text:
        return
    in_string = False
    escape = False
    stack: list[str] = []
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
    if _is_json_fragment(cleaned):
        return cleaned
    for candidate in _iter_json_fragments(cleaned):
        if _is_json_fragment(candidate):
            return candidate
    return cleaned


def _sanitize_json_like(text: str) -> Tuple[str, bool]:
    """
    Attempt minimal repair of near-JSON while keeping valid JSON intact.
    Returns (possibly_modified_text, changed_flag).
    """
    if not text:
        return text, False
    original = text

    # Normalize smart quotes
    t = (
        text.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
    )

    # Remove trailing commas before } or ]
    t = re.sub(r",\s*([}\]])", r"\1", t)

    # Escape literal newlines/tabs inside quoted strings
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


def _parse_json_str(raw: str) -> Tuple[Dict[str, Any], bool]:
    """
    Extract, sanitize, and load JSON. Returns (data, repaired_flag).
    """
    extracted = _extract_json(raw or "")
    sanitized, changed = _sanitize_json_like(extracted)
    try:
        data = json.loads(sanitized)
        return data, changed
    except json.JSONDecodeError:
        # Last-chance: trailing commas
        repaired = re.sub(r",\s*([}\]])", r"\1", sanitized)
        data = json.loads(repaired)
        return data, True


# =========================
# Light helpers (non-forcing)
# =========================

def _safe_preview(s: str, limit: int = 300) -> str:
    if not s:
        return ""
    s = s.strip().replace("\n", " ")
    return (s[:limit] + "…") if len(s) > limit else s


def _collect_hints(doc_text: str) -> Dict[str, List[str]]:
    """
    Collect multi-match, optional hints from plain text.
    These are purely advisory and can be ignored by the model.
    """
    hints: Dict[str, List[str]] = {}

    # invoice number (very loose patterns)
    inv_candidates = re.findall(r"(?:INVOICE[^0-9A-Za-z]{0,5})?No\.?|№\s*[:\s-]*([A-Za-z0-9\-_/]+)", doc_text, flags=re.I)
    if inv_candidates:
        hints["invoice_no"] = [c for c in inv_candidates if c]

    # invoice date (various shapes; keep raw matches)
    date_candidates = re.findall(
        r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}|"
        r"\d{1,2}\s+[A-Za-z]{3,12}\s+\d{4})\b",
        doc_text,
        flags=re.I,
    )
    if date_candidates:
        hints["invoice_date"] = list(dict.fromkeys(date_candidates))  # de-dupe preserving order

    # incoterms (just capture whole phrases with INCOTERMS)
    inco_candidates = re.findall(r"\b(INCOTERMS\s*\d{4})\b", doc_text, flags=re.I)
    if inco_candidates:
        hints["incoterms"] = list(dict.fromkeys(inco_candidates))

    # container and B/L (loose)
    cont_candidates = re.findall(r"\b(CONTAINER[:\s-]*[A-Z0-9]+)\b", doc_text, flags=re.I)
    if cont_candidates:
        hints["container"] = cont_candidates
    bl_candidates = re.findall(r"\b(B\/L\s*NUMBER[:\s-]*[A-Z0-9]+)\b", doc_text, flags=re.I)
    if bl_candidates:
        hints["bl_number"] = bl_candidates

    # buyer/seller blocks – capture header lines
    buyer_candidates = re.findall(r"\bBUYER\/CONSIGNEE[:\s-]+(.+)", doc_text, flags=re.I)
    if buyer_candidates:
        hints["buyer"] = buyer_candidates
    seller_candidates = re.findall(r"\bSELLER\/SHIPPER[:\s-]+(.+)", doc_text, flags=re.I)
    if seller_candidates:
        hints["seller"] = seller_candidates

    return hints


def _find_table_like_tokens(tokens: Any) -> List[Dict[str, Any]]:
    """
    Return tokens that *look* like they may contain table content (e.g., <table>...).
    We do not parse or enforce any structure; we just pass these raw to the products model.
    """
    if not isinstance(tokens, list):
        return []
    candidates: List[Dict[str, Any]] = []
    for t in tokens:
        try:
            text = t.get("text", "")
            if not isinstance(text, str):
                continue
            if "<table" in text.lower() or "</tr>" in text.lower() or "</td>" in text.lower():
                candidates.append(t)
                continue
            # also admit tokens with many delimiters (very rough heuristic)
            if text.count("|") >= 3 or text.count("\t") >= 3:
                candidates.append(t)
        except Exception:
            continue
    return candidates


def _split_template_fields(fields: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Produce a deep copy of fields without 'products'; return (main_only, has_products).
    """
    main_copy = deepcopy(fields or {})
    has_products = isinstance(fields, dict) and ("products" in fields)
    if has_products:
        main_copy.pop("products", None)
    return main_copy, has_products


def _is_leaf_field(d: Dict[str, Any]) -> bool:
    return isinstance(d, dict) and "value" in d


def _prepare_prompt_template(node: Any) -> Any:
    """
    Deep-copy helper that removes bbox/page/confidence metadata for prompt consumption.
    """
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
    """
    Render tokens as `token_id:\ntext` blocks for the LLM prompt.
    """
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
        clean_values = [str(v).strip() for v in values if isinstance(v, str) and v.strip()]
        if not clean_values:
            continue
        joined = "; ".join(dict.fromkeys(clean_values))  # preserve order, drop duplicates
        lines.append(f"{field} (candidates): {joined}")
    return lines


def _split_curated_hints(hints_text: str) -> Tuple[str, str]:
    """
    Split curated hint lines into (main_lines_text, product_lines_text),
    where product lines start with 'products'.
    """
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


def _compose_field_hints_block(curated_text: str, extra_lines: List[str]) -> str:
    parts: List[str] = []
    if curated_text:
        parts.append(curated_text.strip())
    if extra_lines:
        parts.append("\n".join(extra_lines))
    combined = "\n\n".join(part for part in parts if part)
    if combined and len(combined) > MAX_HINTS_TEXT_CHARS:
        return combined[:MAX_HINTS_TEXT_CHARS]
    return combined


def _strip_colon_label(value: str) -> str:
    """
    Rough rule: if a colon ':' exists, remove everything up to the first colon, then trim a single space.
    'A: B: C' -> 'B: C'
    """
    if not isinstance(value, str):
        return value
    idx = value.find(":")
    if idx == -1:
        return value
    # drop prefix including colon
    remainder = value[idx + 1 :]
    # drop only one leading space if present
    if remainder.startswith(" "):
        remainder = remainder[1:]
    return remainder


def _strip_labels_in_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Walk any dict structure looking for leaf objects {'value', 'bbox', 'token_refs'}
    and apply _strip_colon_label to the 'value'. Returns (modified_payload, count_stripped).
    """
    count = 0

    def visit(node: Any) -> None:
        nonlocal count
        if isinstance(node, dict):
            if _is_leaf_field(node):
                orig = node.get("value", "")
                if isinstance(orig, str) and ":" in orig:
                    node["value"] = _strip_colon_label(orig)
                    count += 1
            else:
                for v in node.values():
                    visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(payload)
    return payload, count


# =========================
# LLM call builders
# =========================

def _build_messages_main(tokens: Any,
                         fields_main_only: Dict[str, Any],
                         hints: Dict[str, List[str]],
                         curated_hints_text: Optional[str] = None) -> list:
    user_blocks: List[Dict[str, Any]] = []

    fields_template = _prepare_prompt_template(fields_main_only or {})
    fields_main_json = json.dumps(fields_template, ensure_ascii=False)
    if len(fields_main_json) > MAX_TEMPLATE_JSON_CHARS:
        fields_main_json = fields_main_json[:MAX_TEMPLATE_JSON_CHARS]
    user_blocks.append({
        "type": "text",
        "text": f"=== FIELDS TEMPLATE ===\n{fields_main_json}\n=== END FIELDS TEMPLATE ===",
    })

    dynamic_hint_lines = _format_dynamic_hint_lines(hints or {})
    hints_block = _compose_field_hints_block(curated_hints_text or "", dynamic_hint_lines)
    if hints_block:
        user_blocks.append({
            "type": "text",
            "text": f"=== FIELD HINTS ===\n{hints_block}\n=== END FIELD HINTS ===",
        })

    tokens_text = _format_tokens_for_prompt(tokens)
    if len(tokens_text) > MAX_TOKENS_JSON_CHARS:
        tokens_text = tokens_text[:MAX_TOKENS_JSON_CHARS]
    user_blocks.append({
        "type": "text",
        "text": f"=== RAW TOKENS ===\n{tokens_text}\n=== END RAW TOKENS ===",
    })

    messages = [
        {"role": "system", "content": PROMPT_MAIN},
        {"role": "user", "content": user_blocks},
    ]
    return messages


def _build_messages_products(tokens: Any,
                             product_template: Dict[str, Any],
                             table_like_tokens: List[Dict[str, Any]],
                             curated_hints_text: Optional[str] = None) -> list:
    user_blocks: List[Dict[str, Any]] = []

    product_template_json = json.dumps(_prepare_prompt_template(product_template or {}), ensure_ascii=False)
    if len(product_template_json) > MAX_TEMPLATE_JSON_CHARS:
        product_template_json = product_template_json[:MAX_TEMPLATE_JSON_CHARS]
    user_blocks.append({
        "type": "text",
        "text": f"=== PRODUCT TEMPLATE ===\n{product_template_json}\n=== END PRODUCT TEMPLATE ===",
    })

    hints_block = _compose_field_hints_block(curated_hints_text or "", [])
    if hints_block:
        user_blocks.append({
            "type": "text",
            "text": f"=== FIELD HINTS ===\n{hints_block}\n=== END FIELD HINTS ===",
        })

    tokens_text = _format_tokens_for_prompt(tokens)
    if len(tokens_text) > MAX_TOKENS_JSON_CHARS:
        tokens_text = tokens_text[:MAX_TOKENS_JSON_CHARS]
    user_blocks.append({
        "type": "text",
        "text": f"=== RAW TOKENS ===\n{tokens_text}\n=== END RAW TOKENS ===",
    })

    table_text = _format_table_candidates(table_like_tokens)
    if table_text:
        if len(table_text) > MAX_TABLE_TOKENS_CHARS:
            table_text = table_text[:MAX_TABLE_TOKENS_CHARS]
        user_blocks.append({
            "type": "text",
            "text": f"=== TABLE CANDIDATES ===\n{table_text}\n=== END TABLE CANDIDATES ===",
        })

    messages = [
        {"role": "system", "content": PROMPT_PRODUCTS},
        {"role": "user", "content": user_blocks},
    ]
    return messages


def _dump_messages(doc_id: str, branch: str, model: str, messages: list) -> None:
    """Write a plain-text dump of the exact prompt sent to the LLM.

    The file is written under base_dir/prompts as <doc_id>_<branch>.txt
    """
    try:
        if _PROMPT_DUMP_DIR is None:
            return
        lines: List[str] = []
        lines.append(f"MODEL: {model}")
        lines.append(f"BRANCH: {branch}")
        lines.append("")
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            lines.append(f"=== {role.upper()} ===")
            if isinstance(content, str):
                lines.append(content)
            elif isinstance(content, list):
                for i, part in enumerate(content, start=1):
                    ptype = part.get("type") if isinstance(part, dict) else type(part).__name__
                    lines.append(f"-- part {i} ({ptype}) --")
                    if isinstance(part, dict):
                        txt = part.get("text")
                        if isinstance(txt, str):
                            lines.append(txt)
                        else:
                            lines.append(str(part))
                    else:
                        lines.append(str(part))
            else:
                lines.append(str(content))
            lines.append("")
        payload = "\n".join(lines)
        out_path = _PROMPT_DUMP_DIR / f"{doc_id}_{branch.lower()}_prompt.txt"
        out_path.write_text(payload, encoding="utf-8")
    except Exception:
        logger.warning("Failed to dump prompt (doc_id=%s, branch=%s)", doc_id, branch, exc_info=True)


def _llm_responses(messages: list, model: str, timeout: int = 300) -> str:
    payload: Dict[str, Any] = {
        "model": model,
        "input": _messages_to_input_text(messages),
        "temperature": 0,
    }
    if LLM_REASONING_EFFORT:
        payload["reasoning"] = {"effort": LLM_REASONING_EFFORT}

    url = LLM_BASE_URL.rstrip("/") + "/responses"
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid JSON response: {raw[:200]}") from exc

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data["error"])

    content = _extract_responses_text(data)
    return content


def _llm_chat(messages: list, model: str, timeout: int = 300) -> str:
    """
    Single-shot chat completion call; returns the message content (str).
    """
    assert client is not None, "LLM client not initialized"
    if _supports_responses_reasoning(model):
        return _llm_responses(messages=messages, model=model, timeout=timeout)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        timeout=timeout,
    )

    print("OTVEEET", resp.choices[0].message.content.strip())

    return (resp.choices[0].message.content or "").strip()


def _llm_json_with_retries(messages: list, model: str, branch: str, timeout: int = 300) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    """
    Calls LLM and parses JSON with retries. Returns (payload, repaired_flag, raw_text).
    On retries, appends a corrective user message to enforce strict JSON.
    """
    last_raw: Optional[str] = None
    for attempt in range(1, max(1, MAX_LLM_RETRIES) + 1):
        try:
            msgs = deepcopy(messages)
            if attempt > 1:
                correction = {
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": (
                            "Previous output was not valid JSON. Return strictly valid JSON only, "
                            "no markdown, no comments. Ensure all internal quotes are escaped."
                        )
                    }],
                }
                msgs.append(correction)
            raw = _llm_chat(msgs, model=model, timeout=timeout)
            last_raw = raw
            if _DETAILED:
                logger.debug("%s attempt %d raw (%d chars): %s", branch, attempt, len(raw or ""), _brief(raw or ""))
            data, repaired = _parse_json_str(raw)
            return data, repaired, raw
        except Exception as exc:
            logger.warning("%s attempt %d failed to parse: %s", branch, attempt, exc)
            continue
    return None, False, last_raw


# =========================
# Merge & validation
# =========================

def _ensure_leaf_arrays(node: Dict[str, Any]) -> None:
    """
    Ensure that any leaf field has 'bbox' and 'token_refs' arrays present.
    """
    if not isinstance(node, dict):
        return
    for key, val in node.items():
        if _is_leaf_field(val):
            val.setdefault("bbox", [])
            val.setdefault("token_refs", [])
        elif isinstance(val, dict):
            _ensure_leaf_arrays(val)


def _build_token_lookup(tokens: Any) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    if not isinstance(tokens, list):
        return lookup
    for item in tokens:
        if not isinstance(item, dict):
            continue
        token_id = item.get("id")
        if token_id is None:
            continue
        lookup[str(token_id)] = item
    return lookup


def _normalize_token_refs(raw_refs: Any) -> List[str]:
    if not raw_refs:
        return []
    if isinstance(raw_refs, str):
        return [raw_refs]
    if isinstance(raw_refs, list):
        refs: List[str] = []
        for ref in raw_refs:
            if ref is None:
                continue
            refs.append(str(ref))
        return refs
    return [str(raw_refs)]


def _token_confidence(token: Dict[str, Any]) -> Optional[float]:
    if not isinstance(token, dict):
        return None
    value = token.get("conf")
    if value is None:
        return None
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if conf < 0.0:
        conf = 0.0
    elif conf > 1.0:
        conf = 1.0
    return conf


def _token_bbox(token: Dict[str, Any]) -> Optional[List[float]]:
    bbox = token.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return [float(coord) for coord in bbox]
        except (TypeError, ValueError):
            return None
    return None


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


def _attach_token_metadata(node: Any, lookup: Dict[str, Dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if _is_leaf_field(node):
            refs = _normalize_token_refs(node.get("token_refs"))
            if not refs:
                node["token_refs"] = []
                return
            token = None
            for ref in refs:
                token = lookup.get(ref)
                if token:
                    refs = [str(ref)]
                    break
            if not token:
                node["token_refs"] = refs
                return
            node["token_refs"] = [str(token.get("id", refs[0]))]
            bbox = _token_bbox(token)
            if bbox is not None:
                node["bbox"] = bbox
            confidence = _token_confidence(token)
            if confidence is not None:
                node["confidence"] = confidence
            page = _token_page(token)
            if page is not None:
                node["page"] = page
        else:
            for value in node.values():
                _attach_token_metadata(value, lookup)
    elif isinstance(node, list):
        for item in node:
            _attach_token_metadata(item, lookup)

def _merge_main_and_products(template_fields: Dict[str, Any],
                             main_payload: Optional[Dict[str, Any]],
                             products_payload: Optional[Dict[str, Any]],
                             product_template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Start from a deep copy of the full template fields, apply main updates, then overwrite products if provided.
    Guarantees final shape matches the template (including products subtree when present in template).
    """
    result = deepcopy(template_fields or {})

    # apply main fields (no products)
    if isinstance(main_payload, dict):
        fields_data = main_payload.get("fields") if "fields" in main_payload else main_payload
        if isinstance(fields_data, dict):
            for k, v in fields_data.items():
                if k == "products":
                    continue
                if k in result and isinstance(result[k], dict) and _is_leaf_field(result[k]) and isinstance(v, dict):
                    if "value" in v:
                        result[k]["value"] = v.get("value", result[k].get("value", ""))
                    if "bbox" in v:
                        result[k]["bbox"] = v.get("bbox", result[k].get("bbox", []))
                    if "token_refs" in v:
                        result[k]["token_refs"] = v.get("token_refs", result[k].get("token_refs", []))
                elif k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    # nested sections
                    for nk, nv in v.items():
                        if nk in result[k] and isinstance(result[k][nk], dict) and _is_leaf_field(result[k][nk]) and isinstance(nv, dict):
                            if "value" in nv:
                                result[k][nk]["value"] = nv.get("value", result[k][nk].get("value", ""))
                            if "bbox" in nv:
                                result[k][nk]["bbox"] = nv.get("bbox", result[k][nk].get("bbox", []))
                            if "token_refs" in nv:
                                result[k][nk]["token_refs"] = nv.get("token_refs", result[k][nk].get("token_refs", []))

    # ensure leaf arrays present after main
    _ensure_leaf_arrays(result)

    # apply/overwrite products if provided and template supports it
    if "products" in result and product_template is not None:
        if isinstance(products_payload, dict):
            prods = products_payload.get("products", products_payload)
            if isinstance(prods, dict) and prods:
                # rebuild products strictly from payload keys
                final_products: Dict[str, Any] = {}
                for pkey, pval in prods.items():
                    struct = deepcopy(product_template)
                    if isinstance(pval, dict):
                        # apply known leaves
                        for leaf_key, leaf_tmpl in struct.items():
                            if leaf_key in pval and isinstance(pval[leaf_key], dict):
                                cand = pval[leaf_key]
                                if "value" in cand:
                                    struct[leaf_key]["value"] = cand.get("value", "")
                                if "bbox" in cand:
                                    struct[leaf_key]["bbox"] = cand.get("bbox", [])
                                if "token_refs" in cand:
                                    struct[leaf_key]["token_refs"] = cand.get("token_refs", [])
                    # ensure arrays exist
                    _ensure_leaf_arrays(struct)
                    final_products[pkey] = struct
                result["products"] = final_products
            else:
                # keep template's products shape as-is (likely empty dict)
                pass
        else:
            # no products payload; keep template's shape (often empty)
            pass

    # final safety: ensure arrays exist everywhere
    _ensure_leaf_arrays(result)
    return result


def _validate_fields_against_template(fields: Dict[str, Any],
                                      product_template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Non-blocking validation meta (counts only).
    """
    meta = {
        "missing_leaf_arrays": 0,
        "products_count": 0,
        "products_incomplete": 0,
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _is_leaf_field(node):
                if "bbox" not in node or not isinstance(node.get("bbox"), list):
                    meta["missing_leaf_arrays"] += 1
                if "token_refs" not in node or not isinstance(node.get("token_refs"), list):
                    meta["missing_leaf_arrays"] += 1
            else:
                for v in node.values():
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(fields)

    if product_template and isinstance(fields.get("products"), dict):
        products = fields["products"]
        meta["products_count"] = len(products)
        for p in products.values():
            if isinstance(p, dict):
                for key in product_template.keys():
                    if key not in p:
                        meta["products_incomplete"] += 1

    return meta


# =========================
# FastAPI endpoint
# =========================

@app.post("/v1/fill", response_model=FillerResponse)
async def fill(request: FillerRequest) -> FillerResponse:
    # Request summary
    try:
        tokens_len = len(request.tokens) if isinstance(request.tokens, list) else (len(request.tokens or []) if hasattr(request.tokens, "__len__") else None)
    except Exception:
        tokens_len = None
    logger.info(
        "Fill request: doc_id=%s, type=%s, file=%s, text_len=%s, tokens_len=%s",
        request.doc_id,
        getattr(request.doc_type, "value", str(request.doc_type)),
        request.file_name or "",
        len(request.doc_text or ""),
        tokens_len,
    )
    template_def = get_template_definition(request.doc_type)
    full_template_fields: Dict[str, Any] = deepcopy(template_def.get("fields", {}))
    product_template: Optional[Dict[str, Any]] = template_def.get("product_template")

    # Split template fields
    fields_main_only, has_products = _split_template_fields(full_template_fields)
    logger.info(
        "Template: has_products=%s, product_template_keys=%s",
        has_products,
        (len(product_template) if isinstance(product_template, dict) else 0),
    )

    # Optional, non-forcing hints (multi-match lists)
    hints = _collect_hints(request.doc_text or "")
    # Load curated doc-type hints (plain text)
    curated_hints_text = get_hints_text(request.doc_type, base_dir=HINTS_EN_DIR) or get_hints_text(request.doc_type)
    main_hints_text, product_hints_text = _split_curated_hints(curated_hints_text)

    # Build and run MAIN call
    msgs_main = _build_messages_main(
        tokens=request.tokens,
        fields_main_only=fields_main_only,
        hints=hints,
        curated_hints_text=main_hints_text,
    )
    _dump_messages(request.doc_id, "MAIN", LLM_MODEL_MAIN, msgs_main)
    if _DETAILED:
        logger.debug(
            "MAIN messages built: blocks=%s, sys_prompt_len=%s, user_preview=%s",
            len(msgs_main[1]["content"]) if isinstance(msgs_main, list) and len(msgs_main) > 1 else "?",
            len(PROMPT_MAIN),
            _brief_json(msgs_main[1]["content"] if isinstance(msgs_main, list) and len(msgs_main) > 1 else msgs_main),
        )

    main_raw: Optional[str] = None
    main_payload: Optional[Dict[str, Any]] = None
    main_repaired = False
    main_payload, main_repaired, main_raw = _llm_json_with_retries(
        messages=msgs_main,
        model=LLM_MODEL_MAIN,
        branch="MAIN",
    )
    if isinstance(main_payload, dict):
        try:
            print("BEFORE STRIP", main_payload)
            main_payload, stripped_count = _strip_labels_in_payload(main_payload)
            print("AFTER STRIP", main_payload, stripped_count)
        except Exception:
            stripped_count = 0
        logger.info("Main branch OK (doc_id=%s, repaired=%s, labels_stripped=%d)",
                    request.doc_id, main_repaired, stripped_count)
        if _DETAILED:
            try:
                logger.debug("MAIN parsed keys: %s", list(main_payload.keys()))
                logger.debug("MAIN parsed preview: %s", _brief_json(main_payload))
            except Exception:
                pass
    else:
        logger.warning("Main branch failed after %d attempt(s) (doc_id=%s)", max(1, MAX_LLM_RETRIES), request.doc_id)
        main_payload = None  # will merge as template-empty

    # Build and run PRODUCTS call (sequential; only if template includes products)
    products_raw: Optional[str] = None
    products_payload: Optional[Dict[str, Any]] = None
    products_repaired = False
    if has_products and product_template is not None:
        table_like = _find_table_like_tokens(request.tokens)
        products_tokens = request.tokens
        if table_like:
            products_tokens = []
        msgs_products = _build_messages_products(
            tokens=products_tokens,
            product_template=product_template,
            table_like_tokens=table_like,
            curated_hints_text=product_hints_text,
        )
        _dump_messages(request.doc_id, "PRODUCTS", LLM_MODEL_PRODUCTS, msgs_products)
        if _DETAILED:
            logger.debug(
                "PRODUCTS messages built: blocks=%s, sys_prompt_len=%s, table_like=%d, user_preview=%s",
                len(msgs_products[1]["content"]) if isinstance(msgs_products, list) and len(msgs_products) > 1 else "?",
                len(PROMPT_PRODUCTS),
                len(table_like or []),
                _brief_json(msgs_products[1]["content"] if isinstance(msgs_products, list) and len(msgs_products) > 1 else msgs_products),
            )
        products_payload, products_repaired, products_raw = _llm_json_with_retries(
            messages=msgs_products,
            model=LLM_MODEL_PRODUCTS,
            branch="PRODUCTS",
        )
        if isinstance(products_payload, dict):
            try:
                products_payload, p_stripped = _strip_labels_in_payload(products_payload)
            except Exception:
                p_stripped = 0
            logger.info("Products branch OK (doc_id=%s, repaired=%s, labels_stripped=%d, table_tokens=%d)",
                        request.doc_id, products_repaired, p_stripped, len(table_like))
            if _DETAILED:
                try:
                    p_root = products_payload.get("products", {}) if isinstance(products_payload, dict) else {}
                    logger.debug("PRODUCTS keys: %s", list(p_root.keys()) if isinstance(p_root, dict) else type(p_root))
                    logger.debug("PRODUCTS parsed preview: %s", _brief_json(products_payload))
                except Exception:
                    pass
        else:
            logger.warning("Products branch failed after %d attempt(s) (doc_id=%s)", max(1, MAX_LLM_RETRIES), request.doc_id)
            products_payload = None

    # Merge branches into the exact final shape expected by downstream
    merged_fields = _merge_main_and_products(
        template_fields=full_template_fields,
        main_payload=main_payload,
        products_payload=products_payload,
        product_template=product_template,
    )
    token_lookup = _build_token_lookup(request.tokens)
    if token_lookup:
        _attach_token_metadata(merged_fields, token_lookup)
        _ensure_leaf_arrays(merged_fields)

    # Post-merge visibility
    try:
        merged_products = merged_fields.get("products", {}) if isinstance(merged_fields, dict) else {}

        logger.info(
            "Merged result: products_count=%d, main_present=%s, products_present=%s",
            len(merged_products) if isinstance(merged_products, dict) else 0,
            isinstance(main_payload, dict),
            isinstance(products_payload, dict),
        )
        if isinstance(products_payload, dict) and (not isinstance(merged_products, dict) or len(merged_products) == 0):
            logger.warning("Products payload parsed but merged products are empty; check template.product_template and payload keys")
        if _DETAILED:
            logger.debug("Merged fields preview: %s", _brief_json(merged_fields))
    except Exception:
        pass

    # Validation meta (non-blocking)
    validation_meta = _validate_fields_against_template(merged_fields, product_template)

    return FillerResponse(
        doc_id=request.doc_id,
        fields=merged_fields,
        meta={
            "source": "llm",
            "template": request.doc_type.value,
            "main": {
                "repaired": main_repaired,
                "fallback": main_payload is None,
            },
            "products": {
                "repaired": products_repaired,
                "fallback": products_payload is None,
                "count": len(merged_fields.get("products", {})) if isinstance(merged_fields.get("products"), dict) else 0,
            },
            "validation": validation_meta,
        },
    )
