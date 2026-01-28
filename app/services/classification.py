from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple
import logging
import os

from app.core.enums import DocumentType

logger = logging.getLogger(__name__)
_CLASSIFICATION_DEBUG = os.getenv("SUPPLYHUB_CLASSIFICATION_DEBUG", "").lower() in {"1", "true", "yes", "on"}
_PROFORMA_PRIORITY_RE = re.compile(r"(?i)\bproforma[\s-]+invoice\b")
_PACKING_LIST_PRIORITY_RE = re.compile(r"(?i)\bpacking\s+list\b")
_PRICE_LIST_2_PRIORITY_RE = re.compile(r"(?i)\bprice\s+per\s+kg\b")
_EXPORT_DECL_PRIORITY_RE = re.compile(
    r"(?i)\bdocumento\s+unico\s+de\s+salida\b|\bservicio\s+nacional\s+de\s+aduanas\b|\bexport\s+declaration\b"
)
_T1_PRIORITY_RE = re.compile(
    r"(?i)ihracat\s+refakat\s+belgesi|export\s+accompanying\s+document|transit\s+accompanying\s+document"
)
_VET_CERT_HEADER_RE = re.compile(r"(?i)\bveterinar\w*\s+certificate\b|ветеринар\w*\s+сертификат")
_VET_CERT_NUMBER_RE = re.compile(r"(?i)\bcertificate\s*(?:no|number)\b|сертификат\s*№")


# Keyword patterns per document type.
# We split them into per-token (single-word) and full-text (multi-word) checks.
KEYWORDS: Dict[DocumentType, List[str]] = {
    DocumentType.INVOICE: [
        r"(?i)\binvoice\b",
        r"(?i)инвойс\b",
        r"(?i)сч[её]т[-\s]?фактура\b",
        r"(?i)счет[-\s]?фактура\b",
        r"(?i)fatura\b",
        r"(?i)factura\b",
    ],
    DocumentType.EXPORT_DECLARATION: [
        r"(?i)export\s+declaration",
        r"(?i)customs\s+declaration",
        r"(?:????????????????|????????????????)",
        r"(?:???????\s*?[??]\s*?[?]\s*?[?]\s*?[??][??])",
        r"(?:?[?]\s*?[?]\s*?[??][??])",
        r"(?i)экспортная\s+декларация",
        r"(?i)таможенная\s+декларация",
        r"(?i)ihracat\s+beyannamesi",
        r"(?i)gumruk\s+beyannamesi",
        r"(?i)declaracion\s+de\s+exportacion",
        r"(?i)declaracion\s+aduanera",
    ],
    DocumentType.PACKING_LIST: [
        r"(?i)packing\s+list",
        r"(?i)упаковочный\s+лист",
        r"(?i)упаковочная\s+ведомость",
        r"(?i)paket\s+listesi",
        r"(?i)paketleme\s+listesi",
        r"(?i)lista\s+de\s+empaque",
        r"(?i)lista\s+de\s+embalaje",
        r"(?:???|???|????|????)",
    ],
    DocumentType.BILL_OF_LANDING: [
        r"(?i)bill\s+of\s+landing",
        r"(?i)bill\s+of\s+lading",
        r"(?i)\bB/L\b",
        r"(?i)\bsea[\s-]*way[\s-]*bill\b",
        r"(?i)коносамент",
        r"(?i)бортовой\s+коносамент",
        r"(?i)konsimento",
        r"(?i)deniz\s+konsimentosu",
        r"(?i)conocimiento\s+de\s+embarque",
        r"(?:??|??|????|????)",
    ],
    DocumentType.PRICE_LIST_1: [
        r"(?i)price\s*list",
        r"(?i)прайс[\s-]*лист",
        r"(?i)прейскурант",
        r"(?i)fiyat\s+listesi",
        r"(?i)lista\s+de\s+precios",
        r"(?:???|???|???|???)",
    ],
    DocumentType.PRICE_LIST_2: [
        r"(?i)price\s*list",
        r"(?i)прайс[\s-]*лист",
        r"(?i)прейскурант",
        r"(?i)fiyat\s+listesi",
        r"(?i)lista\s+de\s+precios",
        r"(?:???|???|???|???)",
    ],
    DocumentType.QUALITY_CERTIFICATE: [
        r"(?i)quality\s+certificate",
        r"(?i)сертификат\s+качества",
        r"(?i)качественный\s+сертификат",
        r"(?i)kalite\s+sertifikas?",
        r"(?i)certificado\s+de\s+calidad",
        r"(?:????|????|????|????)",
    ],
    DocumentType.CERTIFICATE_OF_ORIGIN: [
        r"(?i)certificate\s+of\s+origin",
        r"(?i)сертификат\s+происхождения",
        r"(?i)сертификат\s+о\s+происхождении",
        r"(?i)mensei\s+sertifikas?",
        r"(?i)orijin\s+sertifikas?",
        r"(?i)certificado\s+de\s+origen",
        r"(?:?????|?????|????|????)",
    ],
    DocumentType.VETERINARY_CERTIFICATE: [
        r"(?i)veterinary\s+certificate",
        r"(?i)ветеринарный\s+сертификат",
        r"(?i)ветеринарное\s+свидетельство",
        r"(?i)veteriner\s+sertifikas?",
        r"(?i)certificado\s+veterinario",
        r"(?:????|????|??????|??????)",
    ],
    DocumentType.PROFORMA: [
        r"(?i)\bproforma(?:[\s-]+invoice)?\b",
        r"(?i)проформа\s+счёт",
        r"(?i)проформа\s+счет",
        r"(?i)проформа\s+инвойс",
        r"(?i)proforma\s+fatura",
        r"(?i)proforma\s+factura",
        r"(?:????|????|????|????)",
    ],
    DocumentType.T1: [
        r"(?i)ihracat\s+refakat\s+belgesi",
        r"(?i)export\s+accompanying\s+document",
        r"(?i)transit\s+accompanying\s+document",
        r"(?i)\bT1\b",
        r"(?i)\bIRB\b",
        r"(?i)\bMRN\b",
    ],
    # Contract parts (content-based; filename not required).
    DocumentType.CONTRACT_1: [
        r"(?i)\bhereinafter\s+referred\s+to\s+as\s+the\s+buyer\b",
        r"(?i)\bhereinafter\s+referred\s+to\s+as\s+the\s+seller\b",
        r"(?i)\bsubject\s+of\s+the\s+contract\b",
        r"(?i)\bprice\s+and\s+total\s+value\s+of\s+the\s+contract\b",
        r"(?i)\bterms\s+of\s+delivery\b",
        r"(?i)\bименуем\w*\s+в\s+дальнейшем\s+покупател\w*\b",
        r"(?i)\bименуем\w*\s+в\s+дальнейшем\s+продавц\w*\b",
        r"(?i)\bименуем\w*\b",
        r"(?i)\bконтракт\b",
        r"(?i)\bдоговор\b",
        r"(?i)contract\s+no",
    ],
    DocumentType.CONTRACT_2: [
        r"(?i)\bpayment\s+shall\s+be\s+made\b",
        r"(?i)\bpayment\b.{0,40}\bmade\b",
        r"(?i)\bpayment\b.{0,40}\bmay\s+be\b",
        r"(?i)\bpayment\b.{0,40}\badvance\b",
        r"(?i)\bterm[s]?\s+of\s+payment\b",
        r"(?i)\bусловия\s+платежа\b",
        r"(?i)\bоплата\s+осуществляется\b",
        r"(?i)\bоплата\b.{0,40}\bосуществляется\b",
        r"(?i)\bоплата\b.{0,40}\bпредоплат",
    ],
    DocumentType.CONTRACT_3: [
        r"(?i)\blegal\s+addresses\s+of\s+the\s+parties\b",
        r"(?i)\bюридические\s+адреса\s+сторон\b",
    ],
}

def _sanitize_keywords(raw: Dict[DocumentType, List[str]]) -> Dict[DocumentType, List[str]]:
    sanitized: Dict[DocumentType, List[str]] = {}
    for doc_type, patterns in raw.items():
        clean: List[str] = []
        for pattern in patterns:
            try:
                re.compile(pattern)
                clean.append(pattern)
            except re.error:
                logger.warning("Skipping invalid regex pattern for %s: %s", doc_type, pattern)
        sanitized[doc_type] = clean
    return sanitized

# Validate patterns once to avoid runtime regex errors.
SANITIZED_KEYWORDS = _sanitize_keywords(KEYWORDS)


def _split_patterns(patterns: List[str]) -> Tuple[List[str], List[str]]:
    """Split patterns into single-token and full-text buckets."""
    single_word = []
    multi_word = []
    for pattern in patterns:
        if r"\s" in pattern:
            multi_word.append(pattern)
        else:
            single_word.append(pattern)
    return single_word, multi_word


def classify_document(tokens: Iterable[Dict[str, str]], file_name: str | None = None) -> DocumentType:
    scores: Counter[DocumentType] = Counter()
    matched_patterns: Dict[DocumentType, List[str]] = {}

    token_texts = [token.get("text", "").lower() for token in tokens if token.get("text", "")]
    full_text = " ".join(token_texts)
    header_text = " ".join(token_texts[:80])
    if _PROFORMA_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=PROFORMA (proforma invoice)", file_name or "<unknown>")
        return DocumentType.PROFORMA
    if _PACKING_LIST_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=PACKING_LIST (packing list)", file_name or "<unknown>")
        return DocumentType.PACKING_LIST
    if _T1_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=T1 (T1 header)", file_name or "<unknown>")
        return DocumentType.T1
    if _EXPORT_DECL_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info(
                "Classification override: file=%s doc_type=EXPORT_DECLARATION (declaration header)",
                file_name or "<unknown>",
            )
        return DocumentType.EXPORT_DECLARATION
    if _VET_CERT_HEADER_RE.search(header_text) or (
        _VET_CERT_HEADER_RE.search(full_text) and _VET_CERT_NUMBER_RE.search(full_text)
    ):
        if _CLASSIFICATION_DEBUG:
            logger.info(
                "Classification override: file=%s doc_type=VETERINARY_CERTIFICATE (veterinary certificate)",
                file_name or "<unknown>",
            )
        return DocumentType.VETERINARY_CERTIFICATE
    if _PRICE_LIST_2_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=PRICE_LIST_2 (price per kg)", file_name or "<unknown>")
        return DocumentType.PRICE_LIST_2

    per_token_patterns: Dict[DocumentType, List[str]] = {}
    full_text_patterns: Dict[DocumentType, List[str]] = {}
    for doc_type, patterns in SANITIZED_KEYWORDS.items():
        single, multi = _split_patterns(patterns)
        per_token_patterns[doc_type] = single
        full_text_patterns[doc_type] = multi

    for text in token_texts:
        for doc_type, patterns in per_token_patterns.items():
            for pattern in patterns:
                try:
                    if re.search(pattern, text):
                        scores[doc_type] += 1
                        if _CLASSIFICATION_DEBUG:
                            seen = matched_patterns.setdefault(doc_type, [])
                            if pattern not in seen:
                                seen.append(pattern)
                        break
                except re.error:
                    logger.warning("Invalid regex pattern skipped at runtime for %s: %s", doc_type, pattern)

    for doc_type, patterns in full_text_patterns.items():
        for pattern in patterns:
            try:
                if re.search(pattern, full_text):
                    scores[doc_type] += 1
                    if _CLASSIFICATION_DEBUG:
                        seen = matched_patterns.setdefault(doc_type, [])
                        if pattern not in seen:
                            seen.append(pattern)
                    break
            except re.error:
                logger.warning("Invalid regex pattern skipped at runtime for %s: %s", doc_type, pattern)

    if not scores:
        if file_name:
            logger.info("Classification: file=%s doc_type=UNKNOWN (no matches)", file_name)
        return DocumentType.UNKNOWN

    doc_type = scores.most_common(1)[0][0]
    file_label = file_name or "<unknown>"
    logger.info("Classification: file=%s doc_type=%s", file_label, doc_type.value)

    if _CLASSIFICATION_DEBUG:
        top_scores = scores.most_common(5)
        score_text = ", ".join(f"{dt.value}={count}" for dt, count in top_scores)
        logger.info("Classification scores: file=%s %s", file_label, score_text)
        if matched_patterns:
            match_parts: List[str] = []
            for dt, _ in top_scores:
                patterns = matched_patterns.get(dt, [])
                if patterns:
                    match_parts.append(f"{dt.value}:[{'; '.join(patterns)}]")
            if match_parts:
                logger.info("Classification matches: file=%s %s", file_label, " | ".join(match_parts))

    return doc_type


def flatten_tokens(ocr_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "tokens" in ocr_payload and isinstance(ocr_payload["tokens"], list):
        return list(ocr_payload["tokens"])

    tokens: List[Dict[str, Any]] = []
    for page in ocr_payload.get("pages", []):
        tokens.extend(page.get("tokens", []))
    return tokens
