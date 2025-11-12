from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.core.enums import DocumentType


# Mapping of document types to their hint filenames
_DOC_MAPPING: Dict[DocumentType, str] = {
    DocumentType.INVOICE: "invoice_hints.json",
    DocumentType.EXPORT_DECLARATION: "export_declaration_hints.json",
    DocumentType.PACKING_LIST: "packing_list_hints.json",
    DocumentType.BILL_OF_LANDING: "bill_of_landing_hints.json",
    DocumentType.PRICE_LIST_1: "price_list_1_hints.json",
    DocumentType.PRICE_LIST_2: "price_list_2_hints.json",
    DocumentType.QUALITY_CERTIFICATE: "quality_certificate_hints.json",
    DocumentType.CERTIFICATE_OF_ORIGIN: "certificate_of_origin_hints.json",
    DocumentType.VETERINARY_CERTIFICATE: "veterinary_certificate_hints.json",
    DocumentType.PROFORMA: "proforma_hints.json",
    DocumentType.SPECIFICATION: "specification_hints.json",
    DocumentType.CMR: "cmr_hints.json",
}

_BASE_DIR = Path(__file__).resolve().parent

# Simple in-process cache of flattened hint text per doc type
_CACHE: Dict[DocumentType, str] = {}


def _flatten(obj: Any) -> List[str]:
    """Flatten mixed JSON (dict/list/str/number) into a list of text lines."""
    lines: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (list, tuple)):
                for item in v:
                    if item is None:
                        continue
                    if isinstance(item, (dict, list)):
                        for sub in _flatten(item):
                            lines.append(f"{k}: {sub}")
                    else:
                        s = str(item).strip()
                        if s:
                            lines.append(f"{k}: {s}")
            elif isinstance(v, dict):
                for sub in _flatten(v):
                    lines.append(f"{k}: {sub}")
            else:
                s = str(v).strip() if v is not None else ""
                if s:
                    # include key for context
                    lines.append(f"{k}: {s}")
        return lines
    if isinstance(obj, (list, tuple)):
        for item in obj:
            if item is None:
                continue
            if isinstance(item, (dict, list)):
                lines.extend(_flatten(item))
            else:
                s = str(item).strip()
                if s:
                    lines.append(s)
        return lines
    # primitives
    if obj is None:
        return []
    s = str(obj).strip()
    return [s] if s else []


def get_hints_text(doc_type: DocumentType) -> str:
    """Return flattened plain-text hints for the given document type.

    If no hint file exists or it cannot be parsed, returns an empty string.
    """
    if doc_type in _CACHE:
        return _CACHE[doc_type]

    fname = _DOC_MAPPING.get(doc_type)
    if not fname:
        _CACHE[doc_type] = ""
        return ""

    path = _BASE_DIR / fname
    if not path.exists():
        _CACHE[doc_type] = ""
        return ""

    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except Exception:
        _CACHE[doc_type] = ""
        return ""

    lines = _flatten(data)
    text = "\n".join(line for line in lines if line)
    _CACHE[doc_type] = text
    return text

