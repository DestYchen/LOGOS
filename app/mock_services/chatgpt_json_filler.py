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
    "- Include 'token_refs' when obvious; otherwise leave [].\n"
    "- If uncertain for a field, leave it empty.\n"
    "- Hints (if provided) are optional and may be ignored if they conflict with the document.\n"
    "Output strictly valid JSON. No extra keys, no comments."
)

PROMPT_PRODUCTS = (
    "You extract ONLY product rows from OCR text/tokens.\n"
    "Return ONLY a JSON object with keys: {'doc_id': string, 'products': object}.\n"
    "- Create product_1, product_2, ... for the actual product rows you detect (ignore totals/summary rows).\n"
    "- For each product_N, include EVERY child field from <template_product>. If unknown, set value to '' and arrays []\n"
    "- Copy values EXACTLY from the document (no paraphrase). Include 'token_refs' when obvious; otherwise [].\n"
    "- Table-like tokens are provided raw; infer rows as needed. Do not invent data.\n"
    "Output strictly valid JSON. No extra keys, no comments."
)


# =========================
# Logging setup
# =========================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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
    template_def = get_template_definition(request.doc_type)
    full_template_fields: Dict[str, Any] = deepcopy(template_def.get("fields", {}))
    product_template: Optional[Dict[str, Any]] = template_def.get("product_template")

    # Split template fields
    fields_main_only, has_products = _split_template_fields(full_template_fields)

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

    main_raw: Optional[str] = None
    main_payload: Optional[Dict[str, Any]] = None
    main_repaired = False
    try:
        main_raw = _llm_chat(msgs_main, model=LLM_MODEL_MAIN)
        data, repaired = _parse_json_str(main_raw)
        main_payload = data
        main_repaired = repaired
        # post-parse colon label stripping
        main_payload, stripped_count = _strip_labels_in_payload(main_payload)
        logger.info("Main branch OK (doc_id=%s, repaired=%s, labels_stripped=%d)",
                    request.doc_id, main_repaired, stripped_count)
    except Exception as exc:
        logger.warning("Main branch failed (doc_id=%s): %s", request.doc_id, exc)
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
        try:
            products_raw = _llm_chat(msgs_products, model=LLM_MODEL_PRODUCTS)
            pdata, prepaired = _parse_json_str(products_raw)
            products_payload = pdata
            products_repaired = prepaired
            # post-parse colon label stripping
            products_payload, p_stripped = _strip_labels_in_payload(products_payload)
            logger.info("Products branch OK (doc_id=%s, repaired=%s, labels_stripped=%d, table_tokens=%d)",
                        request.doc_id, products_repaired, p_stripped, len(table_like))
        except Exception as exc:
            logger.warning("Products branch failed (doc_id=%s): %s", request.doc_id, exc)
            products_payload = None

    # Merge branches into the exact final shape expected by downstream
    merged_fields = _merge_main_and_products(
        template_fields=full_template_fields,
        main_payload=main_payload,
        products_payload=products_payload,
        product_template=product_template,
    )

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
