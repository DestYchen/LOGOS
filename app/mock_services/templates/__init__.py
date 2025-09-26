from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.core.enums import DocumentType

from .loader import load_template_definition

_TEMPLATE_CACHE: Dict[DocumentType, Dict[str, Any]] = {}


def get_template_definition(doc_type: DocumentType) -> Dict[str, Any]:
    if doc_type not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[doc_type] = load_template_definition(doc_type)
    return _TEMPLATE_CACHE[doc_type]
