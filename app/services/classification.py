from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple
import logging
import os

import httpx

from app.core.config import get_settings
from app.core.enums import DocumentType

logger = logging.getLogger(__name__)
_CLASSIFICATION_DEBUG = os.getenv("SUPPLYHUB_CLASSIFICATION_DEBUG", "").lower() in {"1", "true", "yes", "on"}
settings = get_settings()
_LLM_CLASSIFIER_DISABLED_LOGGED = False
_PROFORMA_PRIORITY_RE = re.compile(r"(?i)\bproforma[\s-]+invoice\b")
_PACKING_LIST_PRIORITY_RE = re.compile(r"(?i)\bpacking\s+list\b")
_SPECIFICATION_PRIORITY_RE = re.compile(
    "(?i)\\b(?:specification|\\u0441\\u043f\\u0435\\u0446\\u0438\\u0444\\u0438\\u043a\\u0430\\u0446\\u0438\\u044f)\\b"
    "\\s*(?:no\\.?|n\\.?|#|\\u2116)\\s*[A-Za-z0-9-]+"
)
_CONTRACT_SIGNAL_RE = re.compile(
    "(?i)\\bcontract\\b|\\b(?:\\u043a\\u043e\\u043d\\u0442\\u0440\\u0430\\u043a\\u0442|\\u0434\\u043e\\u0433\\u043e\\u0432\\u043e\\u0440)\\w*\\b"
)
_INVOICE_HEADER_STRONG_RE = re.compile(
    r"(?i)\bcommercial\s+invoice\b|\binvoice\s*(?:no|number)\b|\binvoice\s+date\b"
)
_PRICE_LIST_PER_KG_RE = re.compile(
    r"(?i)\b(?:unit\s+price|price)\s*(?:per|/)\s*kgs?\b"
    r"|\b(?:usd|eur|rmb|cny)\s*/\s*kgs?\b"
)
_PRICE_LIST_PER_PACK_RE = re.compile(
    r"(?i)\b(?:unit\s+price|price)\s*(?:per|/)\s*"
    r"(?:bag|bags|pack|packs|package|packages|carton|cartons|box|boxes|case|cases|sack|sacks|ctn|ctns)\b"
    r"|\b(?:usd|eur|rmb|cny)\s*/\s*"
    r"(?:bag|bags|pack|packs|package|packages|carton|cartons|box|boxes|case|cases|sack|sacks|ctn|ctns)\b"
)
_PRICE_LIST_HEADER_RE = re.compile(
    r"(?i)\bprice\s*list\b|\bfiyat\s+listesi\b|\blista\s+de\s+precios\b"
)
_CMR_PRIORITY_RE = re.compile(r"(?i)\binternational\s+consignment\s+note\b|\bconsignment\s+note\b|\bCMR\b")
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
    DocumentType.CMR: [
        r"(?i)\bCMR\b",
        r"(?i)international\s+consignment\s+note",
        r"(?i)\bconsignment\s+note\b",
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
    DocumentType.SPECIFICATION: [
        r"(?i)\bspecification\b",
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
        r"(?i)\bon\s+behalf\s+of\s+the\s+buyer\b",
        r"(?i)\bon\s+behalf\s+of\s+the\s+seller\b",
        r"(?i)\bgeneral\s+director\b",
        r"(?i)\bbeneficiary\'?s\s+bank\b",
        r"(?i)\bswift\b",
        r"(?i)\b(?:\u043e\u0442\s+\u0438\u043c\u0435\u043d\u0438)\s+\u043f\u043e\u043a\u0443\u043f\u0430\u0442\u0435\u043b\u044f\b",
        r"(?i)\b(?:\u043e\u0442\s+\u0438\u043c\u0435\u043d\u0438)\s+\u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430\b",
        r"(?i)\b\u0433\u0435\u043d\u0435\u0440\u0430\u043b\u044c\u043d\u044b\u0439\s+\u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440\b",
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


def _pick_price_list_type(header_text: str, full_text: str) -> Tuple[DocumentType | None, str | None]:
    if not (_PRICE_LIST_HEADER_RE.search(header_text) or _PRICE_LIST_HEADER_RE.search(full_text)):
        return None, None

    pack_in_header = bool(_PRICE_LIST_PER_PACK_RE.search(header_text))
    kg_in_header = bool(_PRICE_LIST_PER_KG_RE.search(header_text))
    if kg_in_header and not pack_in_header:
        return DocumentType.PRICE_LIST_1, "price per kg"
    if pack_in_header and not kg_in_header:
        return DocumentType.PRICE_LIST_2, "price per pack"
    if kg_in_header and pack_in_header:
        return DocumentType.PRICE_LIST_1, "price per kg"

    pack_in_full = bool(_PRICE_LIST_PER_PACK_RE.search(full_text))
    kg_in_full = bool(_PRICE_LIST_PER_KG_RE.search(full_text))
    if kg_in_full and not pack_in_full:
        return DocumentType.PRICE_LIST_1, "price per kg"
    if pack_in_full and not kg_in_full:
        return DocumentType.PRICE_LIST_2, "price per pack"
    if kg_in_full and pack_in_full:
        return DocumentType.PRICE_LIST_1, "price per kg"

    return None, None


def _normalize_doc_type_value(raw: str | None) -> DocumentType | None:
    if not raw:
        return None
    token = str(raw).strip().split()[0].strip("`\"' ")
    if not token:
        return None
    token_upper = token.upper()
    if token_upper in ("CT-3", "CT_3"):
        return DocumentType.CT_3
    for doc_type in DocumentType:
        if token_upper == doc_type.value.upper():
            return doc_type
        if token_upper == doc_type.name.upper():
            return doc_type
    alt = token_upper.replace("-", "_")
    for doc_type in DocumentType:
        if alt == doc_type.value.upper() or alt == doc_type.name.upper():
            return doc_type
    return None


def _score_contract_parts(full_text: str) -> Dict[DocumentType, int]:
    scores: Dict[DocumentType, int] = {}
    for doc_type in (DocumentType.CONTRACT_1, DocumentType.CONTRACT_2, DocumentType.CONTRACT_3):
        count = 0
        for pattern in SANITIZED_KEYWORDS.get(doc_type, []):
            try:
                if re.search(pattern, full_text):
                    count += 1
            except re.error:
                logger.warning("Invalid regex pattern skipped at runtime for %s: %s", doc_type, pattern)
        scores[doc_type] = count
    return scores


def _pick_contract_part(full_text: str) -> DocumentType | None:
    scores = _score_contract_parts(full_text)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return None
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def _classify_document_llm(tokens: Iterable[Dict[str, str]], file_name: str | None = None) -> DocumentType | None:
    endpoint = settings.doc_classifier_endpoint
    if not endpoint:
        global _LLM_CLASSIFIER_DISABLED_LOGGED
        if not _LLM_CLASSIFIER_DISABLED_LOGGED:
            logger.info("Doc classifier endpoint not configured; skipping LLM classification.")
            _LLM_CLASSIFIER_DISABLED_LOGGED = True
        return None

    raw_texts = [token.get("text", "") for token in tokens if token.get("text", "")]
    if not raw_texts:
        return None

    header_text = " ".join(raw_texts[:80]).strip()
    doc_text = " ".join(raw_texts).strip()
    max_chars = settings.doc_classifier_max_text_chars
    if max_chars and len(doc_text) > max_chars:
        doc_text = doc_text[:max_chars]

    payload: Dict[str, Any] = {
        "doc_id": file_name or "",
        "file_name": file_name,
        "header_text": header_text,
        "doc_text": doc_text,
    }

    try:
        logger.info(
            "Classification (LLM request): file=%s endpoint=%s header_len=%s text_len=%s",
            file_name or "<unknown>",
            endpoint,
            len(header_text),
            len(doc_text),
        )
        with httpx.Client(timeout=float(settings.doc_classifier_timeout)) as client:
            response = client.post(str(endpoint), json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning(
            "Doc classifier request failed; falling back to regex for %s",
            file_name or "<unknown>",
            exc_info=True,
        )
        return None

    doc_type_raw: Any | None = None
    if isinstance(data, dict):
        doc_type_raw = data.get("doc_type") or data.get("type") or data.get("docType")
        if isinstance(doc_type_raw, dict):
            doc_type_raw = doc_type_raw.get("value")
    elif isinstance(data, str):
        doc_type_raw = data

    normalized = _normalize_doc_type_value(doc_type_raw)
    logger.info(
        "Classification (LLM response): file=%s doc_type=%s",
        file_name or "<unknown>",
        (normalized.value if normalized else DocumentType.UNKNOWN.value),
    )
    return normalized


def classify_document(tokens: Iterable[Dict[str, str]], file_name: str | None = None) -> DocumentType:
    token_texts = [token.get("text", "").lower() for token in tokens if token.get("text", "")]
    full_text = " ".join(token_texts)
    header_text = " ".join(token_texts[:80])
    invoice_header_strong = bool(_INVOICE_HEADER_STRONG_RE.search(header_text))
    if _PROFORMA_PRIORITY_RE.search(header_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=PROFORMA (proforma invoice)", file_name or "<unknown>")
        return DocumentType.PROFORMA
    if invoice_header_strong:
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=INVOICE (invoice header)", file_name or "<unknown>")
        return DocumentType.INVOICE
    contract_part = _pick_contract_part(full_text)
    contract_signal = bool(_CONTRACT_SIGNAL_RE.search(header_text) or _CONTRACT_SIGNAL_RE.search(full_text))
    if contract_part and contract_signal:
        if _CLASSIFICATION_DEBUG:
            logger.info(
                "Classification override: file=%s doc_type=%s (contract signals)",
                file_name or "<unknown>",
                contract_part.value,
            )
        return contract_part
    if _PACKING_LIST_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=PACKING_LIST (packing list)", file_name or "<unknown>")
        return DocumentType.PACKING_LIST
    if _SPECIFICATION_PRIORITY_RE.search(header_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=SPECIFICATION (specification header)", file_name or "<unknown>")
        return DocumentType.SPECIFICATION
    price_list_type, price_list_reason = _pick_price_list_type(header_text, full_text)
    if price_list_type:
        if _CLASSIFICATION_DEBUG:
            logger.info(
                "Classification override: file=%s doc_type=%s (%s)",
                file_name or "<unknown>",
                price_list_type.value,
                price_list_reason,
            )
        return price_list_type

    llm_doc_type = _classify_document_llm(tokens, file_name=file_name)
    if llm_doc_type and llm_doc_type != DocumentType.UNKNOWN:
        file_label = file_name or "<unknown>"
        logger.info("Classification (LLM): file=%s doc_type=%s", file_label, llm_doc_type.value)
        return llm_doc_type

    scores: Counter[DocumentType] = Counter()
    matched_patterns: Dict[DocumentType, List[str]] = {}
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
    if _CMR_PRIORITY_RE.search(full_text):
        if _CLASSIFICATION_DEBUG:
            logger.info("Classification override: file=%s doc_type=CMR (consignment note)", file_name or "<unknown>")
        return DocumentType.CMR
    if _VET_CERT_HEADER_RE.search(header_text) or (
        _VET_CERT_HEADER_RE.search(full_text) and _VET_CERT_NUMBER_RE.search(full_text)
    ):
        if _CLASSIFICATION_DEBUG:
            logger.info(
                "Classification override: file=%s doc_type=VETERINARY_CERTIFICATE (veterinary certificate)",
                file_name or "<unknown>",
            )
        return DocumentType.VETERINARY_CERTIFICATE
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
