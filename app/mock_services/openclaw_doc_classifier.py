from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.enums import DocumentType


logger = logging.getLogger(__name__)

OPENCLAW_CLASSIFIER_BASE_URL = os.getenv("OPENCLAW_CLASSIFIER_BASE_URL", "http://127.0.0.1:18789/v1/responses")
OPENCLAW_CLASSIFIER_MODEL = os.getenv("OPENCLAW_CLASSIFIER_MODEL", os.getenv("OPENCLAW_MODEL", "openclaw/default"))
OPENCLAW_API_TOKEN = os.getenv("OPENCLAW_API_TOKEN", "")
OPENCLAW_CLASSIFIER_TIMEOUT = float(os.getenv("OPENCLAW_CLASSIFIER_TIMEOUT", os.getenv("OPENCLAW_TIMEOUT", "120")))
OPENCLAW_CLASSIFIER_MAX_TEXT_CHARS = int(os.getenv("OPENCLAW_CLASSIFIER_MAX_TEXT_CHARS", "20000"))


class ClassifierRequest(BaseModel):
    doc_id: Optional[str] = None
    file_name: Optional[str] = None
    header_text: Optional[str] = None
    doc_text: Optional[str] = None


class ClassifierResponse(BaseModel):
    doc_id: Optional[str] = None
    doc_type: str


app = FastAPI(title="OpenClaw Document Classifier Adapter")


@app.post("/v1/classify", response_model=ClassifierResponse)
async def classify(request: ClassifierRequest) -> ClassifierResponse:
    header_text = (request.header_text or "").strip()
    doc_text = (request.doc_text or "").strip()
    if OPENCLAW_CLASSIFIER_MAX_TEXT_CHARS and len(doc_text) > OPENCLAW_CLASSIFIER_MAX_TEXT_CHARS:
        doc_text = doc_text[:OPENCLAW_CLASSIFIER_MAX_TEXT_CHARS]

    logger.info(
        "openclaw_doc_classifier request doc_id=%s file=%s header_len=%s text_len=%s",
        request.doc_id or "",
        request.file_name or "",
        len(header_text),
        len(doc_text),
    )

    raw = await _call_openclaw(header_text=header_text, doc_text=doc_text, file_name=request.file_name)
    doc_type = _normalize_doc_type(raw)
    logger.info("openclaw_doc_classifier result doc_id=%s doc_type=%s", request.doc_id or "", doc_type)
    return ClassifierResponse(doc_id=request.doc_id, doc_type=doc_type)


async def _call_openclaw(*, header_text: str, doc_text: str, file_name: Optional[str]) -> str:
    if not OPENCLAW_API_TOKEN:
        raise HTTPException(status_code=500, detail="openclaw_api_token_not_configured")

    payload = {
        "model": OPENCLAW_CLASSIFIER_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": _build_prompt(header_text=header_text, doc_text=doc_text, file_name=file_name),
                    }
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENCLAW_API_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=OPENCLAW_CLASSIFIER_TIMEOUT) as client:
            response = await client.post(OPENCLAW_CLASSIFIER_BASE_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"openclaw_request_failed:{exc}") from exc

    if response.status_code >= 400:
        logger.warning("OpenClaw classifier failed status=%s body=%s", response.status_code, response.text[:1000])
        raise HTTPException(status_code=502, detail="openclaw_request_failed")

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="openclaw_invalid_json") from exc

    return _extract_response_text(data)


def _build_prompt(*, header_text: str, doc_text: str, file_name: Optional[str]) -> str:
    allowed_types = ", ".join(_allowed_doc_type_values())
    return (
        "You are a document type classifier for logistics and foreign-trade documents.\n"
        "Return exactly one token from the allowed list and nothing else.\n"
        "If unsure, return UNKNOWN.\n\n"
        "For contracts, do not return CONTRACT. Choose CONTRACT_1, CONTRACT_2, or CONTRACT_3 by content. "
        "Return UNKNOWN if the contract part is unclear.\n\n"
        f"Allowed types:\n{allowed_types}\n\n"
        f"File name:\n{file_name or ''}\n\n"
        f"Header text:\n{header_text}\n\n"
        f"Document text:\n{doc_text}\n"
    )


def _allowed_doc_type_values() -> list[str]:
    return [doc_type.value for doc_type in DocumentType if doc_type != DocumentType.CONTRACT]


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


def _normalize_doc_type(raw: str) -> str:
    if not raw:
        return DocumentType.UNKNOWN.value
    token = raw.strip().split()[0].strip("`\"' ")
    if not token:
        return DocumentType.UNKNOWN.value
    token_upper = token.upper()
    if token_upper in ("CT-3", "CT_3"):
        return DocumentType.CT_3.value
    for doc_type in DocumentType:
        if doc_type == DocumentType.CONTRACT:
            continue
        if token_upper == doc_type.value.upper():
            return doc_type.value
        if token_upper == doc_type.name.upper():
            return doc_type.value
    alt = token_upper.replace("-", "_")
    for doc_type in DocumentType:
        if doc_type == DocumentType.CONTRACT:
            continue
        if alt == doc_type.value.upper() or alt == doc_type.name.upper():
            return doc_type.value
    return DocumentType.UNKNOWN.value
