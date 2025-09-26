from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List

from app.core.enums import DocumentType

KEYWORDS = {
    DocumentType.INVOICE: [r"(?i)\binvoice\b"],
    DocumentType.EXPORT_DECLARATION: [r"(?i)export\s+declaration", r"(?i)customs\s+declaration"],
    DocumentType.PACKING_LIST: [r"(?i)packing\s+list"],
    DocumentType.BILL_OF_LANDING: [r"(?i)bill\s+of\s+landing", r"(?i)\bB/L\b"],
    DocumentType.PRICE_LIST_1: [r"(?i)price\s*list\s*1"],
    DocumentType.PRICE_LIST_2: [r"(?i)price\s*list\s*2"],
    DocumentType.QUALITY_CERTIFICATE: [r"(?i)quality\s+certificate"],
    DocumentType.CERTIFICATE_OF_ORIGIN: [r"(?i)certificate\s+of\s+origin"],
    DocumentType.VETERINARY_CERTIFICATE: [r"(?i)veterinary\s+certificate"],
}


def classify_document(tokens: Iterable[Dict[str, str]]) -> DocumentType:
    scores: Counter[DocumentType] = Counter()
    for token in tokens:
        text = token.get("text", "").lower()
        if not text:
            continue
        for doc_type, patterns in KEYWORDS.items():
            if any(re.search(pattern, text) for pattern in patterns):
                scores[doc_type] += 1
    if not scores:
        return DocumentType.UNKNOWN
    return scores.most_common(1)[0][0]


def flatten_tokens(ocr_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "tokens" in ocr_payload and isinstance(ocr_payload["tokens"], list):
        return list(ocr_payload["tokens"])

    tokens: List[Dict[str, Any]] = []
    for page in ocr_payload.get("pages", []):
        tokens.extend(page.get("tokens", []))
    return tokens



