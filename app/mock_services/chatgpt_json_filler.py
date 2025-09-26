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
        "You extract structured data from documents. Fill only the known fields. "
        "You will receive a template describing the exact JSON structure expected. "
        "Return strictly valid JSON matching that template with strings for values, arrays for bbox/token_refs, and dictionaries for nested sections. "
        "Do not add new keys or commentary."
    ),
)
OPENAI_MODEL = "openai/gpt-oss-120b:free"

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
