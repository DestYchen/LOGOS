from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx
from PIL import Image
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789/v1/responses")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw/default")
OPENCLAW_API_TOKEN = os.getenv("OPENCLAW_API_TOKEN", "")
OPENCLAW_TIMEOUT = float(os.getenv("OPENCLAW_TIMEOUT", "300"))
OPENCLAW_TOKEN_CONF = float(os.getenv("OPENCLAW_TOKEN_CONF", "0.70"))
OPENCLAW_OCR_PDF_DPI = int(os.getenv("OPENCLAW_OCR_PDF_DPI", "300"))
OPENCLAW_OCR_MAX_PIXELS = int(os.getenv("OPENCLAW_OCR_MAX_PIXELS", "4000000"))

OCR_PROMPT = os.getenv(
    "OPENCLAW_OCR_PROMPT",
    (
        "Extract all readable text from the supplied document. "
        "Return only the recognized text. Do not summarize, explain, or comment. "
        "Keep the reading order top to bottom and left to right. "
        "Preserve paragraphs and line breaks when possible. "
        "Mark unreadable fragments as [unclear]."
    ),
)


class OCRRequest(BaseModel):
    doc_id: str = Field(..., description="UUID of the document")
    file_path: str = Field(..., description="Absolute path to the uploaded file")
    file_name: Optional[str] = Field(default=None, description="Original filename")
    file_bytes: Optional[str] = Field(default=None, description="Base64-encoded file content")
    file_suffix: Optional[str] = Field(default=None, description="Original file suffix (with dot)")
    langs: Iterable[str] | None = None
    options: dict[str, Any] | None = None


class OCRResponse(BaseModel):
    doc_id: str
    tokens: list[dict[str, Any]]


app = FastAPI(title="OpenClaw OCR Adapter")


@app.post("/v1/ocr", response_model=OCRResponse)
async def run_ocr(request: OCRRequest) -> OCRResponse:
    file_bytes, suffix, filename = _resolve_file(request)
    tokens = await _tokens_from_file(file_bytes=file_bytes, suffix=suffix, filename=filename)
    if not tokens:
        raise HTTPException(status_code=400, detail="empty_document")
    logger.info("openclaw_ocr doc_id=%s tokens=%s", request.doc_id, len(tokens))
    return OCRResponse(doc_id=request.doc_id, tokens=tokens)


def _resolve_file(request: OCRRequest) -> tuple[bytes, str, str]:
    path = Path(request.file_path)
    suffix_candidates = [
        request.file_suffix or "",
        path.suffix or "",
        Path(request.file_name).suffix if request.file_name else "",
    ]
    suffix = next((item for item in suffix_candidates if item), ".pdf").lower()
    filename = request.file_name or path.name or f"document{suffix}"

    if request.file_bytes:
        try:
            return base64.b64decode(request.file_bytes), suffix, filename
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid_file_bytes") from exc

    if path.exists():
        return path.read_bytes(), suffix, filename

    raise HTTPException(status_code=404, detail="file_not_found")


async def _tokens_from_file(*, file_bytes: bytes, suffix: str, filename: str) -> list[dict[str, Any]]:
    if suffix.lower() == ".pdf":
        text = await _call_openclaw(file_bytes=file_bytes, suffix=suffix, filename=filename)
        return _text_to_tokens(text, page=1)

    image_bytes, image_suffix = _maybe_resize_image(file_bytes, suffix)
    text = await _call_openclaw(file_bytes=image_bytes, suffix=image_suffix, filename=filename)
    return _text_to_tokens(text, page=1)


def _maybe_resize_image(file_bytes: bytes, suffix: str) -> tuple[bytes, str]:
    if suffix.lower() not in {".png", ".jpg", ".jpeg"} or OPENCLAW_OCR_MAX_PIXELS <= 0:
        return file_bytes, suffix

    try:
        import io

        image = Image.open(io.BytesIO(file_bytes))
        image.load()
    except Exception:
        logger.debug("Failed to inspect image size for OpenClaw OCR", exc_info=True)
        return file_bytes, suffix

    width, height = image.size
    pixels = width * height
    if pixels <= OPENCLAW_OCR_MAX_PIXELS:
        return file_bytes, suffix

    scale = (OPENCLAW_OCR_MAX_PIXELS / float(pixels)) ** 0.5
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    resized = image.resize(new_size, resampling)
    if resized.mode not in {"RGB", "L"}:
        resized = resized.convert("RGB")
    output = io.BytesIO()
    resized.save(output, format="PNG")
    return output.getvalue(), ".png"


async def _call_openclaw(*, file_bytes: bytes, suffix: str, filename: str) -> str:
    if not OPENCLAW_API_TOKEN:
        raise HTTPException(status_code=500, detail="openclaw_api_token_not_configured")

    media_type = _media_type(suffix)
    payload = {
        "model": OPENCLAW_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": OCR_PROMPT},
                    {
                        "type": "input_file",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "filename": filename,
                            "data": base64.b64encode(file_bytes).decode("ascii"),
                        },
                    },
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENCLAW_API_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=OPENCLAW_TIMEOUT) as client:
            response = await client.post(OPENCLAW_BASE_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"openclaw_request_failed:{exc}") from exc

    if response.status_code >= 400:
        logger.warning("OpenClaw OCR failed status=%s body=%s", response.status_code, response.text[:1000])
        raise HTTPException(status_code=502, detail="openclaw_request_failed")

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="openclaw_invalid_json") from exc

    text = _extract_response_text(data).strip()
    if not text:
        raise HTTPException(status_code=502, detail="openclaw_empty_response")
    return text


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


def _text_to_tokens(text: str, *, page: int) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    token_id = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for word in re.findall(r"\S+", stripped):
            tokens.append(
                {
                    "id": f"p{page}_t{token_id}",
                    "text": word,
                    "conf": OPENCLAW_TOKEN_CONF,
                    "bbox": [0, 0, 0, 0],
                    "page": page,
                    "category": "Text",
                }
            )
            token_id += 1
    return tokens


def _media_type(suffix: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain",
    }.get(suffix.lower(), "application/octet-stream")
