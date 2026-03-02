from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel

from app.core.enums import DocumentType

logger = logging.getLogger(__name__)

# Base URL and API key: keep consistent with chatgpt_json_filler.py
LLM_BASE_URL: str = "http://10.0.0.247:1234/v1"
LLM_API_KEY: str = ""
LLM_MODEL_MAIN: str = "openai/gpt-oss-20b"

MAX_TEXT_CHARS = int(os.getenv("DOC_CLASSIFIER_MAX_TEXT_CHARS", "20000"))
HINTS_PATH = Path(__file__).resolve().parent / "classifier_hints.json"

PROMPT_TEMPLATE = (
    "You are a document type classifier for logistics documents.\n"
    "Return ONLY one token from the allowed list.\n"
    "If unsure, return UNKNOWN.\n\n"
    "Allowed types:\n{allowed_types}\n\n"
    "Hints (optional):\n{hints}\n"
)

PROMPT_CONTRACT_TEMPLATE = (
    "You are a contract page classifier.\n"
    "Return ONLY one token from the allowed list.\n"
    "If unsure, return UNKNOWN.\n\n"
    "Rules:\n"
    "- Prefer CONTRACT_1/CONTRACT_2/CONTRACT_3 when the text matches those hints.\n"
    "- Use CONTRACT only if this is a contract page but it does not match any part hints.\n\n"
    "Allowed types:\n{allowed_types}\n\n"
    "Hints (optional):\n{hints}\n"
)

_CONTRACT_TYPES = {
    DocumentType.CONTRACT.value,
    DocumentType.CONTRACT_1.value,
    DocumentType.CONTRACT_2.value,
    DocumentType.CONTRACT_3.value,
}
_CONTRACT_SIGNAL_RE = re.compile("(?i)\\bcontract\\b|\\b(?:\u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442|\u0434\u043e\u0433\u043e\u0432\u043e\u0440)\\w*\\b")
_PROFORMA_SIGNAL_RE = re.compile(r"\bproforma\b", re.IGNORECASE)
_INVOICE_SIGNAL_RE = re.compile(r"\binvoice\b|\binvoice\s*no\b|\binvoice\s*number\b", re.IGNORECASE)
_INVOICE_HEADER_STRONG_RE = re.compile(
    r"(?i)\bcommercial\s+invoice\b|\binvoice\s*(?:no|number)\b|\binvoice\s+date\b"
)
_SPECIFICATION_SIGNAL_RE = re.compile(
    r"(?:\bspecification\b|\u0441\u043f\u0435\u0446\u0438\u0444\u0438\u043a\u0430\u0446\u0438\u044f)\s*"
    r"(?:no\.?|n\.?|#|\u2116)\s*[A-Za-z0-9-]+",
    re.IGNORECASE,
)

app = FastAPI(title="ChatGPT Document Classifier Adapter")

client: Optional[OpenAI] = None

class ClassifierRequest(BaseModel):
    doc_id: Optional[str] = None
    file_name: Optional[str] = None
    header_text: Optional[str] = None
    doc_text: Optional[str] = None


class ClassifierResponse(BaseModel):
    doc_id: Optional[str] = None
    doc_type: str


@app.on_event("startup")
def init_client() -> None:
    global client
    if client is not None:
        return
    headers = {
        "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
        "X-Title": os.getenv("OPENROUTER_X_TITLE", "Doc Classifier"),
    }
    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        default_headers=headers or None,
    )
    logger.info("Doc classifier client initialized (base_url=%s, model=%s)", LLM_BASE_URL, LLM_MODEL_MAIN)


_HINTS_CACHE: Optional[Dict[str, List[str]]] = None


def _load_hints() -> Dict[str, List[str]]:
    global _HINTS_CACHE
    if _HINTS_CACHE is not None:
        return _HINTS_CACHE
    if not HINTS_PATH.exists():
        _HINTS_CACHE = {}
        return _HINTS_CACHE
    try:
        raw = HINTS_PATH.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            _HINTS_CACHE = {}
            return _HINTS_CACHE
        hints: Dict[str, List[str]] = {}
        for key, value in data.items():
            if isinstance(value, list):
                hints[str(key)] = [str(item) for item in value if item is not None]
        _HINTS_CACHE = hints
    except Exception:
        logger.warning("Failed to load classifier hints", exc_info=True)
        _HINTS_CACHE = {}
    return _HINTS_CACHE


def _format_hints(hints: Dict[str, List[str]]) -> str:
    if not hints:
        return "(none)"
    lines: List[str] = []
    for key in sorted(hints.keys()):
        items = hints.get(key) or []
        for item in items:
            item_str = str(item).strip()
            if item_str:
                lines.append(f"{key}: {item_str}")
    return "\n".join(lines) if lines else "(none)"


def _allowed_types() -> List[str]:
    return [doc_type.value for doc_type in DocumentType]


def _allowed_contract_types() -> List[str]:
    return [
        DocumentType.CONTRACT_1.value,
        DocumentType.CONTRACT_2.value,
        DocumentType.CONTRACT_3.value,
        DocumentType.CONTRACT.value,
        DocumentType.UNKNOWN.value,
    ]


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
        if token_upper == doc_type.value.upper():
            return doc_type.value
        if token_upper == doc_type.name.upper():
            return doc_type.value
    alt = token_upper.replace("-", "_")
    for doc_type in DocumentType:
        if alt == doc_type.value.upper() or alt == doc_type.name.upper():
            return doc_type.value
    return DocumentType.UNKNOWN.value


def _build_messages(header_text: str, doc_text: str) -> List[Dict[str, Any]]:
    allowed_types = ", ".join(_allowed_types())
    hints_block = _format_hints(_load_hints())
    system_prompt = PROMPT_TEMPLATE.format(allowed_types=allowed_types, hints=hints_block)
    user_prompt = f"HEADER:\n{header_text}\n\nTEXT:\n{doc_text}\n"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_contract_messages(header_text: str, doc_text: str) -> List[Dict[str, Any]]:
    allowed_types = ", ".join(_allowed_contract_types())
    hints = _load_hints()
    contract_hints = {
        key: value
        for key, value in hints.items()
        if key in _CONTRACT_TYPES or key.startswith("CONTRACT_")
    }
    hints_block = _format_hints(contract_hints)
    system_prompt = PROMPT_CONTRACT_TEMPLATE.format(allowed_types=allowed_types, hints=hints_block)
    user_prompt = f"HEADER:\n{header_text}\n\nTEXT:\n{doc_text}\n"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _looks_like_contract(header_text: str, doc_text: str) -> bool:
    if _CONTRACT_SIGNAL_RE.search(header_text) or _CONTRACT_SIGNAL_RE.search(doc_text):
        return True
    hints = _load_hints()
    contract_hints = []
    for key in _CONTRACT_TYPES:
        contract_hints.extend(hints.get(key, []))
    lowered = doc_text.lower()
    for hint in contract_hints:
        hint_lower = str(hint).strip().lower()
        if hint_lower and hint_lower in lowered:
            return True
    return False


def _looks_like_proforma(header_text: str, doc_text: str) -> bool:
    if header_text:
        return bool(_PROFORMA_SIGNAL_RE.search(header_text))
    return bool(_PROFORMA_SIGNAL_RE.search(doc_text))


def _looks_like_invoice(header_text: str, doc_text: str) -> bool:
    return bool(_INVOICE_SIGNAL_RE.search(header_text) or _INVOICE_SIGNAL_RE.search(doc_text))


def _looks_like_specification(header_text: str, doc_text: str) -> bool:
    if header_text:
        return bool(_SPECIFICATION_SIGNAL_RE.search(header_text))
    return bool(_SPECIFICATION_SIGNAL_RE.search(doc_text))


def _score_contract_parts(doc_text: str) -> Dict[str, int]:
    hints = _load_hints()
    lowered = doc_text.lower()
    scores: Dict[str, int] = {}
    for part in (DocumentType.CONTRACT_1.value, DocumentType.CONTRACT_2.value, DocumentType.CONTRACT_3.value):
        score = 0
        for hint in hints.get(part, []):
            hint_lower = str(hint).strip().lower()
            if hint_lower and hint_lower in lowered:
                score += 1
        scores[part] = score
    return scores


def _pick_contract_part(doc_text: str) -> Optional[str]:
    scores = _score_contract_parts(doc_text)
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return None
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


@app.post("/v1/classify", response_model=ClassifierResponse)
async def classify(request: ClassifierRequest) -> ClassifierResponse:
    if client is None:
        raise RuntimeError("LLM client not initialized")

    header_text = (request.header_text or "").strip()
    doc_text = (request.doc_text or "").strip()
    if MAX_TEXT_CHARS and len(doc_text) > MAX_TEXT_CHARS:
        doc_text = doc_text[:MAX_TEXT_CHARS]

    logger.info(
        "Doc classifier request: doc_id=%s file=%s header_len=%s text_len=%s",
        request.doc_id or "",
        request.file_name or "",
        len(header_text),
        len(doc_text),
    )

    messages = _build_messages(header_text, doc_text)
    resp = client.chat.completions.create(
        model=LLM_MODEL_MAIN,
        messages=messages,
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    doc_type = _normalize_doc_type(raw)
    proforma_signal = _looks_like_proforma(header_text, doc_text)
    invoice_signal = _looks_like_invoice(header_text, doc_text)
    specification_signal = _looks_like_specification(header_text, doc_text)
    contract_hint_override = _pick_contract_part(doc_text)
    contract_header_signal = bool(_CONTRACT_SIGNAL_RE.search(header_text))
    contract_text_signal = bool(_CONTRACT_SIGNAL_RE.search(doc_text))
    contract_signal = contract_header_signal or (contract_text_signal and contract_hint_override)
    invoice_header_signal = bool(_INVOICE_SIGNAL_RE.search(header_text))
    invoice_header_strong = bool(_INVOICE_HEADER_STRONG_RE.search(header_text))

    if invoice_header_strong and not proforma_signal:
        doc_type = DocumentType.INVOICE.value
        logger.info(
            "Doc classifier override: doc_id=%s doc_type=%s (invoice header)",
            request.doc_id or "",
            doc_type,
        )
        logger.info("Doc classifier result: doc_id=%s doc_type=%s", request.doc_id or "", doc_type)
        return ClassifierResponse(doc_id=request.doc_id, doc_type=doc_type)

    if contract_signal and not invoice_header_signal:
        contract_messages = _build_contract_messages(header_text, doc_text)
        contract_resp = client.chat.completions.create(
            model=LLM_MODEL_MAIN,
            messages=contract_messages,
            temperature=0,
        )
        contract_raw = (contract_resp.choices[0].message.content or "").strip()
        contract_type = _normalize_doc_type(contract_raw)
        if contract_type != DocumentType.UNKNOWN.value:
            doc_type = contract_type
        else:
            doc_type = DocumentType.CONTRACT.value

        hint_override = contract_hint_override
        if hint_override and doc_type in _CONTRACT_TYPES and hint_override != doc_type:
            logger.info(
                "Doc classifier override: doc_id=%s doc_type=%s -> %s (contract hints)",
                request.doc_id or "",
                doc_type,
                hint_override,
            )
            doc_type = hint_override

        logger.info(
            "Doc classifier override: doc_id=%s doc_type=%s (contract header)",
            request.doc_id or "",
            doc_type,
        )
        logger.info("Doc classifier result: doc_id=%s doc_type=%s", request.doc_id or "", doc_type)
        return ClassifierResponse(doc_id=request.doc_id, doc_type=doc_type)

    if proforma_signal and doc_type != DocumentType.PROFORMA.value:
        logger.info(
            "Doc classifier override: doc_id=%s doc_type=%s -> %s (proforma signal)",
            request.doc_id or "",
            doc_type,
            DocumentType.PROFORMA.value,
        )
        doc_type = DocumentType.PROFORMA.value
    elif invoice_signal and doc_type != DocumentType.INVOICE.value:
        logger.info(
            "Doc classifier override: doc_id=%s doc_type=%s -> %s (invoice signal)",
            request.doc_id or "",
            doc_type,
            DocumentType.INVOICE.value,
        )
        doc_type = DocumentType.INVOICE.value
    elif specification_signal and doc_type != DocumentType.SPECIFICATION.value:
        logger.info(
            "Doc classifier override: doc_id=%s doc_type=%s -> %s (specification signal)",
            request.doc_id or "",
            doc_type,
            DocumentType.SPECIFICATION.value,
        )
        doc_type = DocumentType.SPECIFICATION.value

    if (not proforma_signal) and (not invoice_signal) and (not specification_signal) and (
        doc_type in _CONTRACT_TYPES or _looks_like_contract(header_text, doc_text)
    ):
        contract_messages = _build_contract_messages(header_text, doc_text)
        contract_resp = client.chat.completions.create(
            model=LLM_MODEL_MAIN,
            messages=contract_messages,
            temperature=0,
        )
        contract_raw = (contract_resp.choices[0].message.content or "").strip()
        contract_type = _normalize_doc_type(contract_raw)
        if contract_type != DocumentType.UNKNOWN.value:
            doc_type = contract_type

        hint_override = contract_hint_override or _pick_contract_part(doc_text)
        if hint_override and doc_type in _CONTRACT_TYPES and hint_override != doc_type:
            logger.info(
                "Doc classifier override: doc_id=%s doc_type=%s -> %s (contract hints)",
                request.doc_id or "",
                doc_type,
                hint_override,
            )
            doc_type = hint_override

    logger.info("Doc classifier result: doc_id=%s doc_type=%s", request.doc_id or "", doc_type)
    return ClassifierResponse(doc_id=request.doc_id, doc_type=doc_type)
