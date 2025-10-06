from __future__ import annotations

import base64
import logging
import json
import os
import re
import uuid
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import fitz  # type: ignore import-not-found
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services import text_extractor

HARDCODED_OPENROUTER_API_KEY = ""

OCR_PROMPT = os.getenv(
    "CHATGPT_OCR_PROMPT",
    (
        "Please output the layout information from the image, including each layout element's bbox, its category, and the corresponding text content within the bbox."
        "1. Bbox format: [x1, y1, x2, y2]"
        "2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Section-header', 'Table', 'Text', 'Title']."
        "3. Text Extraction & Formatting Rules:"
        "- Table: Format its text as HTML."
        "- All Others (Text, Title, etc.): Format their text as Markdown."
        "4. Constraints:"
        "- The output text must be the original text from the image, with no translation."
        "- All layout elements must be sorted according to human reading order."
        "5. Final Output: The entire output must be a single JSON object with structure:"
        "{\"pages\": [{\"page\": 1, \"tokens\": [{\"category\": string, \"text\": string, \"bbox\": [0,0,0,0]}]} ]}."
    ),
)

OPENAI_MODEL = "mistralai/mistral-small-3.2-24b-instruct:free"

settings = get_settings()
logger = logging.getLogger(__name__)
client: Optional[OpenAI] = None
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


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


app = FastAPI(title="OpenRouter OCR Adapter")


@app.on_event("startup")
def init_client() -> None:
    global client
    if client is None:
        api_key = "".strip()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set and HARDCODED_OPENROUTER_API_KEY is empty")

        client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "http://localhost:8001",
                "X-Title": "My OCR Adapter",
            },
        )


@app.post("/v1/ocr", response_model=OCRResponse)
async def run_ocr(request: OCRRequest) -> OCRResponse:
    path = Path(request.file_path)
    logger.debug("Received OCR request doc_id=%s path=%s file_name=%s suffix=%s has_bytes=%s", request.doc_id, path, request.file_name, request.file_suffix, bool(request.file_bytes))
    try:
        doc_uuid = uuid.UUID(request.doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_doc_id") from exc

    file_bytes: Optional[bytes] = None
    if request.file_bytes:
        try:
            file_bytes = base64.b64decode(request.file_bytes)
            logger.debug("Decoded file_bytes length=%s for doc_id=%s", len(file_bytes), request.doc_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="invalid_file_bytes") from exc

    suffix_candidates = [
        request.file_suffix or "",
        path.suffix or "",
        Path(request.file_name).suffix if request.file_name else "",
    ]
    suffix = next((item for item in suffix_candidates if item), "").lower()
    logger.debug("Resolved suffix=%s path_exists=%s for doc_id=%s", suffix, path.exists(), request.doc_id)

    if settings.use_stub_services:
        temp_path: Optional[Path] = None
        try:
            if not path.exists() and file_bytes is not None:
                fd, tmp_name = tempfile.mkstemp(suffix=suffix if suffix else ".bin")
                os.close(fd)
                temp_path = Path(tmp_name)
                temp_path.write_bytes(file_bytes)
                return OCRResponse(**_stub_ocr(doc_uuid, temp_path))
            return OCRResponse(**_stub_ocr(doc_uuid, path))
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    tokens: List[dict[str, Any]]
    if path.exists():
        if path.suffix.lower() == ".pdf":
            logger.debug("Processing PDF from path=%s doc_id=%s", path, request.doc_id)
            tokens = await _tokens_from_pdf(path, request.doc_id)
        else:
            logger.debug("Processing single file from path=%s doc_id=%s", path, request.doc_id)
            tokens = await _tokens_from_single_file(path, request.doc_id)
    elif file_bytes is not None:
        try:
            logger.debug("Processing bytes input doc_id=%s suffix=%s len=%s", request.doc_id, suffix, len(file_bytes))
            tokens = await _tokens_from_bytes(file_bytes, suffix, request.doc_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid_file_bytes") from exc
    else:
        raise HTTPException(status_code=404, detail="file_not_found")

    logger.debug("Collected tokens=%s for doc_id=%s", len(tokens), request.doc_id)
    if not tokens:
        raise HTTPException(status_code=400, detail="empty_document")
    print(tokens)
    return OCRResponse(doc_id=request.doc_id, tokens=tokens)


async def _tokens_from_pdf(path: Path, doc_id: str, dpi: int = 200, max_pages: int = 40) -> List[dict[str, Any]]:
    tokens: List[dict[str, Any]] = []
    logger.debug("Opening PDF file=%s doc_id=%s", path, doc_id)
    with fitz.open(path) as document:
        if document.page_count == 0:
            return []
        logger.debug("PDF page_count=%s doc_id=%s", document.page_count, doc_id)
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            image_bytes = pix.tobytes("png")
            content = _image_content(image_bytes, ".png")
            page_tokens = await _call_chatgpt_page(doc_id, index + 1, content)
            logger.debug("Collected %s tokens for doc_id=%s page=%s", len(page_tokens), doc_id, index + 1)
            tokens.extend(page_tokens)
    return tokens


async def _tokens_from_pdf_bytes(data: bytes, doc_id: str, dpi: int = 200, max_pages: int = 40) -> List[dict[str, Any]]:
    tokens: List[dict[str, Any]] = []
    with fitz.open(stream=data, filetype="pdf") as document:
        if document.page_count == 0:
            return []
        logger.debug("PDF bytes page_count=%s doc_id=%s", document.page_count, doc_id)
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            image_bytes = pix.tobytes("png")
            content = _image_content(image_bytes, ".png")
            page_tokens = await _call_chatgpt_page(doc_id, index + 1, content)
            logger.debug("Collected %s tokens for doc_id=%s page=%s", len(page_tokens), doc_id, index + 1)
            tokens.extend(page_tokens)
    return tokens


async def _tokens_from_single_file(path: Path, doc_id: str) -> List[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        content = _image_content(path.read_bytes(), suffix)
        logger.debug("Built image content suffix=%s doc_id=%s", suffix, doc_id)
    else:
        extracted = text_extractor.extract_text(path)
        text = extracted.text if extracted else _read_text(path)
        if not text.strip():
            logger.debug("Text payload empty for doc_id=%s", doc_id)
            return []
        content = _text_content(text)
        logger.debug("Built text content length=%s doc_id=%s", len(text), doc_id)

    return await _call_chatgpt_page(doc_id, 1, content)


async def _tokens_from_bytes(data: bytes, suffix: str, doc_id: str) -> List[dict[str, Any]]:
    normalized = (suffix or "").lower()
    if not normalized or normalized == ".pdf":
        try:
            return await _tokens_from_pdf_bytes(data, doc_id)
        except Exception:
            if normalized == ".pdf":
                raise
    if normalized in IMAGE_EXTENSIONS:
        content = _image_content(data, normalized)
        return await _call_chatgpt_page(doc_id, 1, content)
    text = data.decode("utf-8", errors="ignore")
    logger.debug("Decoded bytes to text length=%s doc_id=%s", len(text), doc_id)
    if not text.strip():
        logger.debug("Text payload empty for doc_id=%s (bytes)", doc_id)
        return []
    content = _text_content(text)
    return await _call_chatgpt_page(doc_id, 1, content)


async def _call_chatgpt_page(doc_id: str, page_number: int, content: List[dict[str, Any]]) -> List[dict[str, Any]]:
    logger.debug("Calling LLM for doc_id=%s page=%s with %s parts", doc_id, page_number, len(content))
    data = await _call_chatgpt(doc_id=doc_id, content=content)
    logger.debug("LLM response keys=%s doc_id=%s page=%s", list(data.keys()), doc_id, page_number)

    tokens_raw: List[dict[str, Any]] = []
    if "tokens" in data and isinstance(data["tokens"], list):
        tokens_raw = data["tokens"]
    else:
        pages = data.get("pages", [])
        if pages:
            tokens_raw = pages[0].get("tokens", [])

    tokens: List[dict[str, Any]] = []
    for idx, token in enumerate(tokens_raw):
        text = token.get("text", "")
        if not text:
            continue
        normalized: Dict[str, Any] = {
            "id": token.get("id", f"p{page_number}_t{idx}"),
            "text": text,
            "conf": float(token.get("conf", 0.0)),
            "bbox": token.get("bbox", [0, 0, 0, 0]),
            "page": token.get("page", page_number),
        }
        if "category" in token and token["category"]:
            normalized["category"] = token["category"]
        tokens.append(normalized)
    return tokens


def _messages_from_content(content: List[dict[str, Any]]) -> List[dict[str, Any]]:
    parts: List[dict[str, Any]] = []
    for item in content:
        kind = item.get("type")
        if kind == "input_text":
            parts.append({"type": "text", "text": item["text"]})
        elif kind == "input_image":
            image = item.get("image_url")
            if isinstance(image, str) and image:
                parts.append({"type": "image_url", "image_url": {"url": image}})
    return parts


def _extract_json(s: str) -> str:
    match = re.search(r"\{.*\}", s, re.S)
    return match.group(0) if match else s


async def _call_chatgpt(*, doc_id: str, content: List[dict[str, Any]]) -> dict[str, Any]:
    assert client is not None

    messages = [
        {"role": "system", "content": OCR_PROMPT},
        {"role": "user", "content": _messages_from_content(content)},
    ]

    logger.debug("Invoking OpenRouter model=%s doc_id=%s parts=%s", OPENAI_MODEL, doc_id, len(content))
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0,
    )

    logger.debug("OpenRouter response status usage=%s doc_id=%s", getattr(resp, 'usage', None), doc_id)
    raw = resp.choices[0].message.content or ""
    raw = _extract_json(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="invalid_llm_response") from exc

    if "doc_id" not in data:
        data["doc_id"] = doc_id
    if "tokens" not in data and "pages" not in data:
        data["tokens"] = []
    return data


def _image_content(image_bytes: bytes, suffix: str) -> List[dict[str, Any]]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix.lower(), "image/png")
    return [{"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}]


def _text_content(text: str) -> List[dict[str, Any]]:
    return [{"type": "input_text", "text": text}]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _stub_ocr(doc_id: uuid.UUID, file_path: Path) -> Dict[str, Any]:
    extraction = text_extractor.extract_text(file_path)
    text = extraction.text if extraction else _read_text(file_path)
    tokens = _text_to_tokens(text)
    return {"doc_id": str(doc_id), "tokens": tokens}


def _text_to_tokens(text: str) -> List[dict[str, Any]]:
    tokens: List[dict[str, Any]] = []
    for idx, word in enumerate(text.split()[:500]):
        if not word:
            continue
        tokens.append(
            {
                "id": f"stub_t{idx}",
                "text": word,
                "conf": 1.0,
                "page": 1,
                "bbox": [0, 0, 0, 0],
                "category": "Text",
            }
        )
    return tokens
