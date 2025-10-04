from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Dict, Iterator, Optional

from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel, Field

from app.core.enums import DocumentType
from app.mock_services.templates import get_template_definition

HARDCODED_OPENAI_API_KEY = ""
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
OPENAI_MODEL = "google/gemma-3-27b-it"

client: Optional[OpenAI] = None


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
    print(template_def)
    template_fields = deepcopy(template_def.get("fields", {}))
    product_template = template_def.get("product_template")

    if client is None:
        return FillerResponse(**_stub_fill(request, template_fields, product_template))

    template_json = json.dumps(template_fields, ensure_ascii=False)
    user_content = [
        {"type": "text", "text": f"Document type: {request.doc_type.value}"},
        {"type": "text", "text": f"Template fields: {template_json}"},
        {"type": "text", "text": request.doc_text[:8000]},
    ]
    if request.tokens:
        tokens_preview = json.dumps(request.tokens, ensure_ascii=False)[:4000]
        user_content.append({"type": "input_text", "text": f"OCR tokens: {tokens_preview}"})

    content = [
        {"role": "system", "content": FILLER_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        # response = client.responses.create(model=OPENAI_MODEL, temperature=0, input=content)
        response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=content,
                temperature=0)
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)
    except Exception:
        return FillerResponse(**_stub_fill(request, template_fields, product_template))

    filled_fields = _merge_template(template_fields, product_template, data.get("fields", {}))
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
