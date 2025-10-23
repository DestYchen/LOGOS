from __future__ import annotations

import json
import os
import logging
import re
from copy import deepcopy
from typing import Any, Dict, Iterator, Optional, Tuple, List

from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel
from app.core.enums import DocumentType
from app.mock_services.templates import get_template_definition


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

# System prompts (kept minimal; no forced normalization, no row counts).
PROMPT_MAIN = (
    "You convert OCR text and tokens into structured JSON.\n"
    "Return ONLY a JSON object with keys: {'doc_id': string, 'fields': object}.\n"
    "- Fill ONLY the fields present in <template_fields_main> (no 'products').\n"
    "- Copy values EXACTLY from the document (no guessing, no paraphrase).\n"
    "- Always include 'token_refs' when the field was filled; otherwise leave [].\n"
    "- If uncertain for a field, leave it empty.\n"
    "- Hints (if provided) are optional and may be ignored if they conflict with the document.\n"
    "Output strictly valid JSON. No extra keys, no comments."
)

PROMPT_PRODUCTS = (
    "You extract ONLY product rows from OCR text/tokens.\n"
    "Return ONLY a JSON object with keys: {'doc_id': string, 'products': object}.\n"
    "- Create product_1, product_2, ... for the actual product rows you detect (ignore totals/summary rows).\n"
    "- For each product_N, include EVERY child field from <template_product>. If unknown, set value to '' and arrays []\n"
    "- Copy values EXACTLY from the document (no paraphrase). Always include 'token_refs' when the field was filled; otherwise leave [].\n"
    "- Table-like tokens are provided raw; infer rows as needed. Do not invent data.\n"
    "Output strictly valid JSON. No extra keys, no comments."
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


@app.on_event("startup")
def init_client() -> None:
    global client
    if client is None:
        client = _create_client()
        logger.info("LLM client initialized (base_url=%s, model_main=%s, model_products=%s)",
                    LLM_BASE_URL, LLM_MODEL_MAIN, LLM_MODEL_PRODUCTS)


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

def _build_messages_main(doc_id: str,
                         doc_text: str,
                         tokens: Any,
                         fields_main_only: Dict[str, Any],
                         hints: Dict[str, List[str]]) -> list:
    user_blocks = []
    user_blocks.append({"type": "text", "text": f"<doc_id>\n{doc_id}\n</doc_id>"})
    user_blocks.append({"type": "text", "text": f"<raw_plain_text>\n{doc_text}\n</raw_plain_text>"})

    # include tokens fully if reasonable; otherwise, include as a raw JSON string (the model/tool will handle size)
    try:
        tokens_json = json.dumps(tokens, ensure_ascii=False)
    except Exception:
        tokens_json = str(tokens)
    user_blocks.append({"type": "text", "text": f"<raw_tokens>\n{tokens_json}\n</raw_tokens>"})

    fields_main_json = json.dumps({"fields": fields_main_only}, ensure_ascii=False)
    user_blocks.append({"type": "text", "text": f"<template_fields_main>\n{fields_main_json}\n</template_fields_main>"})

    if hints:
        hints_json = json.dumps(hints, ensure_ascii=False)
        user_blocks.append({"type": "text", "text": f"<hints>(Optional; ignore if conflicting)\n{hints_json}\n</hints>"})

    messages = [
        {"role": "system", "content": PROMPT_MAIN},
        {"role": "user", "content": user_blocks},
    ]
    return messages


def _build_messages_products(doc_id: str,
                             doc_text: str,
                             tokens: Any,
                             product_template: Dict[str, Any],
                             table_like_tokens: List[Dict[str, Any]]) -> list:
    user_blocks = []
    user_blocks.append({"type": "text", "text": f"<doc_id>\n{doc_id}\n</doc_id>"})
    user_blocks.append({"type": "text", "text": f"<raw_plain_text>\n{doc_text}\n</raw_plain_text>"})

    try:
        tokens_json = json.dumps(tokens, ensure_ascii=False)
    except Exception:
        tokens_json = str(tokens)
    user_blocks.append({"type": "text", "text": f"<raw_tokens>\n{tokens_json}\n</raw_tokens>"})

    product_template_json = json.dumps({"product_template": product_template}, ensure_ascii=False)
    user_blocks.append({"type": "text", "text": f"<template_product>\n{product_template_json}\n</template_product>"})

    if table_like_tokens:
        # send raw table-like tokens as-is
        try:
            tbl_json = json.dumps(table_like_tokens, ensure_ascii=False)
        except Exception:
            tbl_json = str(table_like_tokens)
        user_blocks.append({"type": "text", "text": f"<table_candidates>\n{tbl_json}\n</table_candidates>"})

    messages = [
        {"role": "system", "content": PROMPT_PRODUCTS},
        {"role": "user", "content": user_blocks},
    ]
    return messages


def _llm_chat(messages: list, model: str, timeout: int = 300) -> str:
    """
    Single-shot chat completion call; returns the message content (str).
    """
    assert client is not None, "LLM client not initialized"
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        timeout=timeout,
    )
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

    # Build and run MAIN call
    msgs_main = _build_messages_main(
        doc_id=request.doc_id,
        doc_text=request.doc_text or "",
        tokens=request.tokens,
        fields_main_only=fields_main_only,
        hints=hints,
    )
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
            main_payload, stripped_count = _strip_labels_in_payload(main_payload)
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
        msgs_products = _build_messages_products(
            doc_id=request.doc_id,
            doc_text=request.doc_text or "",
            tokens=request.tokens,
            product_template=product_template,
            table_like_tokens=table_like,
        )
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
        doc_id=(main_payload.get("doc_id") if isinstance(main_payload, dict) else request.doc_id),
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
