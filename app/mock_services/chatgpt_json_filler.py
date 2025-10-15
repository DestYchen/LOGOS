from __future__ import annotations

import json
import os
import logging
import re
from copy import deepcopy
from typing import Any, Dict, Iterator, Optional

from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel, Field

from app.core.enums import DocumentType
from app.mock_services.templates import get_template_definition

HARDCODED_OPENAI_API_KEY = "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"
FILLER_PROMPT = os.getenv(
    "CHATGPT_FILLER_PROMPT",
    (
        "INPUTS YOU WILL RECEIVE:"
        "- Document type (string)"
        "- Template fields (a JSON object describing the exact field structure)"
        "- Document text (plain text; OCR output)"
        "- Optionally OCR tokens (for token_refs alignment)"

        "STRICT OUTPUT CONTRACT:"
        "Return a single JSON object with ONLY the following top-level keys:"
        "{"
        "'doc_id': string,"
        "'fields': object"
        "}"

        "- 'doc_id': echo the provided doc_id if present in the input; if not provided, return an empty string ''."
        "- 'fields': ONLY include keys that exist in 'Template fields'. For each included key that represents a leaf field, the value MUST be an object that may contain any subset of:"
        "- 'value': string"
        "- 'bbox': array of numbers (or empty array if unknown)"
        "- 'token_refs': array of token ids/indices (or empty array if unknown)"

        "DO NOT add new keys. DO NOT add commentary. DO NOT repeat or reprint the template."

        "EXTRACTION RULES:"
        "1) Copy values EXACTLY as they appear in the document text (no paraphrasing, no guessing)."
        "2) If a field is absent or uncertain, either:"
        "   - omit that field from 'fields', OR"
        "   - set 'value' to '' and leave 'bbox'/'token_refs' as []."
        "3) If OCR tokens are provided, prefer filling 'token_refs' with the best matching token indices. If uncertain, return []."
        "4) For non-leaf sections (nested objects), ONLY include children that you confidently fill; otherwise omit the whole branch."
        "5) Never invent or normalize formats unless the document explicitly provides them (e.g., keep original date/number formatting)."
        "6) The JSON MUST be strictly valid and parseable. No trailing text."

        "BE CONCISE: output only the JSON object that satisfies the contract above."
    ),
)
OPENAI_MODEL = "qwen/qwen2.5-vl-32b-instruct:free"

client: Optional[OpenAI] = None
logger = logging.getLogger(__name__)




def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
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


class FillerRequest(BaseModel):
    doc_id: str
    doc_type: DocumentType
    doc_text: str
    file_name: Optional[str] = None
    tokens: Optional[Any] = None


class FillerResponse(BaseModel):
    doc_id: str
    fields: Dict[str, Dict[str, Any]]
    meta: Dict[str, Any]


app = FastAPI(title="ChatGPT JSON Filler Adapter")


@app.on_event("startup")
def init_client() -> None:
    global client
    if client is None:
        api_key = HARDCODED_OPENAI_API_KEY.strip()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set and HARDCODED_OPENROUTER_API_KEY is empty")
        

        client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost:8002"),
                "X-Title": os.getenv("OPENROUTER_X_TITLE", "My OCR Adapter"),
            },
        )


@app.post("/v1/fill", response_model=FillerResponse)
async def fill(request: FillerRequest) -> FillerResponse:
    template_def = get_template_definition(request.doc_type)
    template_fields = deepcopy(template_def.get("fields", {}))
    product_template = template_def.get("product_template")

    if client is None:
        return FillerResponse(**_stub_fill(request, template_fields, product_template))

    template_payload: Dict[str, Any] = {"fields": template_fields}
    if product_template is not None:
        template_payload["product_template"] = product_template
    template_json = json.dumps(template_payload, ensure_ascii=False)

    # user_content = [
    #     {"type": "text", "text": f"Document type: {request.doc_type.value}"},
    #     {"type": "text", "text": f"Template fields: {template_json}"},
    #     {"type": "text", "text": request.doc_text[:8000]},
    # ]

    tokens_preview = ""
    if request.tokens:
        tokens_preview = json.dumps(request.tokens, ensure_ascii=False)
        #user_content.append({"type": "input_text", "text": f"OCR tokens: {tokens_preview}"})

    print(tokens_preview)

    plain_text = f'<raw_plain_text>\n{request.doc_text}\n</raw_plain_text>'
    raw_tockens = f"<raw_tokens>\n{tokens_preview}\n</raw_tokens>"
    template_block = f"<template>\n{template_json}\n</template>"

    system_prompt = (
        "You are a system tasked with turning raw OCR data into structured JSON."
        "You receive:"
        "- raw plain-text extracted from the document;"
        "- the OCR tokens with ids, text, bbox, page;"
        "- a JSON template describing which fields must be filled."
        "- when present, a product_template object that shows the structure for items inside the 'products' map."

        "Rules:"
        "1. Only fill the fields present in the template. Leave the others empty."
        "2. For every field you fill:"
        "- value — copy the exact text from the document (no normalization or guessing);"
        "- bbox — use the bounding box from the same token that supplied the value (if the value is composed from several tokens, you may provide multiple bounding boxes or leave it empty if coordinates are unknown);"
        "- token_refs — list the identifiers of the tokens (e.g., ['p1_t4', 'p1_t5']) from which you extracted the value."
        "3. If 'products' is present in the template, you MUST output it as an object where each entry is named product_1, product_2, ..., one per product row. Even when the entire table arrives as a single token (for example <table>...</table>), you must parse it row by row and behave as if each <tr> were separate input."
        "- Count the number of product rows. The number of product_N entries must match exactly."
        "- Each product_N must contain every child field shown in product_template (even if empty)."
        "- If you cannot split rows, still create product_1 with whatever data you have and leave the rest empty."
        "- Any product_N outside fields.products or data inside product_template will be ignored."
        "4. If you are not confident, leave value empty and both bbox and token_refs as empty arrays."
        "5. Output only valid JSON that matches the template exactly. No extra text, comments, or additional keys."
    )
    # content = [
    #     {"role": "system", "content": FILLER_PROMPT},
    #     {"role": "user", "content": user_content},
    # ]

    content = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": plain_text + "\n\n" + raw_tockens + "\n\n" + template_block},
    ]

    debug_payload: Dict[str, Any] = {
        "doc_id": request.doc_id,
        "doc_type": request.doc_type.value,
        "file_name": request.file_name,
        "template_fields": template_fields,
        "doc_text_length": len(request.doc_text or ""),
        "doc_text_preview": request.doc_text[:1000],
    }
    if request.tokens is not None:
        if isinstance(request.tokens, list):
            debug_payload["tokens_count"] = len(request.tokens)
            debug_payload["tokens_preview"] = request.tokens[:5]
        else:
            debug_payload["tokens_type"] = type(request.tokens).__name__
            debug_payload["tokens_repr"] = str(request.tokens)[:1000]

    # print("=== JSON FILLER REQUEST PAYLOAD ===")
    # print(json.dumps(debug_payload, ensure_ascii=False, indent=2))
    # print("=== JSON FILLER MODEL MESSAGE ===")
    # print(json.dumps(content, ensure_ascii=False, indent=2))
    # print("=== END JSON FILLER DEBUG ===")

    raw_response: str | None = None
    try:
        # response = client.responses.create(model=OPENAI_MODEL, temperature=0, input=content)
        response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=content,
                temperature=0,
                timeout=300)
        raw = response.choices[0].message.content or ""
        raw_response = raw
        raw = _extract_json(raw)
        print(raw)
        data = json.loads(raw)
    except Exception as exc:
        logger.exception(
            "JSON filler LLM call failed doc_id=%s type=%s: %s; raw=%r",
            request.doc_id,
            request.doc_type.value,
            exc,
            raw_response,
        )
        return FillerResponse(**_stub_fill(request, template_fields, product_template))

    fields_payload = data.get("fields")
    if not isinstance(fields_payload, dict):
        fields_payload = data

    logger.debug("JSON filler parsed payload doc_id=%s: %s", request.doc_id, fields_payload)

    filled_fields = _merge_template(template_fields, product_template, fields_payload)
    return FillerResponse(
        doc_id=data.get("doc_id", request.doc_id),
        fields=filled_fields,
        meta={"source": "llm", "template": request.doc_type.value},
    )

def _merge_template(
    template_fields: Dict[str, Any],
    product_template: Optional[Dict[str, Any]],
    values: Dict[str, Any],
) -> Dict[str, Any]:
    result = deepcopy(template_fields)

    def apply(target: Dict[str, Any], updates: Dict[str, Any]) -> None:
        for key, target_value in target.items():
            if key == "products" and isinstance(target_value, dict):
                updates_products = updates.get(key, {}) if isinstance(updates, dict) else {}
                if isinstance(updates_products, dict) and product_template is not None:
                    products: Dict[str, Any] = {}
                    for product_key, product_updates in updates_products.items():
                        product_struct = deepcopy(product_template)
                        if isinstance(product_updates, dict):
                            apply(product_struct, product_updates)
                        products[product_key] = product_struct
                    target[key] = products if products else {}
                elif not target_value and product_template is not None:
                    target[key] = {}
            elif isinstance(target_value, dict) and "value" in target_value:
                update_value = updates.get(key, {}) if isinstance(updates, dict) else {}
                if isinstance(update_value, dict):
                    if "value" in update_value:
                        target_value["value"] = update_value.get("value", target_value["value"])
                    if "bbox" in update_value:
                        target_value["bbox"] = update_value.get("bbox", target_value["bbox"])
                    if "token_refs" in update_value:
                        target_value["token_refs"] = update_value.get("token_refs", target_value.get("token_refs", []))
            elif isinstance(target_value, dict):
                update_value = updates.get(key, {}) if isinstance(updates, dict) else {}
                if isinstance(update_value, dict):
                    apply(target_value, update_value)

    apply(result, values or {})
    return result


def _stub_fill(
    request: FillerRequest,
    template_fields: Dict[str, Any],
    product_template: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    words_iter = iter(word for word in request.doc_text.split() if word)
    result_fields = deepcopy(template_fields)

    if "products" in result_fields and product_template is not None and not result_fields["products"]:
        result_fields["products"] = {"product_1": deepcopy(product_template)}

    def populate(target: Dict[str, Any], iterator: Iterator[str]) -> None:
        for key, value in target.items():
            if isinstance(value, dict) and "value" in value:
                value["value"] = next(iterator, "")
                value.setdefault("bbox", [])
                value.setdefault("token_refs", [])
            elif isinstance(value, dict):
                if key == "products" and product_template is not None and not value:
                    value["product_1"] = deepcopy(product_template)
                populate(value, iterator)

    populate(result_fields, words_iter)

    return {
        "doc_id": request.doc_id,
        "fields": result_fields,
        "meta": {"stub": True, "template": request.doc_type.value},
    }


