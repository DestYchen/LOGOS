from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List

from app.core.enums import DocumentType

KEYWORDS_2 = {
    DocumentType.INVOICE: [r"(?i)\binvoice\b"],
    DocumentType.EXPORT_DECLARATION: [r"(?i)export\s+declaration", r"(?i)customs\s+declaration", r"(?:中华人民共和国海关出口货物报关单|中華人民共和國海關出口貨物報關單)"
                                      r"(?:中华人民共和国\s*海[关關]\s*出[口]\s*货[物]\s*报[关關][单單])",r"(?:出[口]\s*货[物]\s*报[关關][单單])"],
    DocumentType.PACKING_LIST: [r"(?i)packing\s+list"],
    DocumentType.BILL_OF_LANDING: [r"(?i)bill\s+of\s+landing", r"(?i)\bB/L\b", r"(?i)\bsea[\s-]*way[\s-]*bill\b"],
    DocumentType.PRICE_LIST_1: [r"(?i)price\s*list"],
    DocumentType.PRICE_LIST_2: [r"(?i)price\s*list"],
    DocumentType.QUALITY_CERTIFICATE: [r"(?i)quality\s+certificate"],
    DocumentType.CERTIFICATE_OF_ORIGIN: [r"(?i)certificate\s+of\s+origin"],
    DocumentType.VETERINARY_CERTIFICATE: [r"(?i)veterinary\s+certificate"],
    DocumentType.PROFORMA: [r"(?i)\bproforma(?:[\s-]+invoice)?\b"],
}

KEYWORDS = {
        DocumentType.INVOICE: [
        r"(?i)\binvoice\b",
        r"(?i)счёт\b", r"(?i)счет\b", r"(?i)инвойс\b", 
        r"(?i)fatura\b",  
        r"(?i)factura\b",  
        r"(?:发票|發票)" 
    ],
    DocumentType.EXPORT_DECLARATION: [
        r"(?i)export\s+declaration", r"(?i)customs\s+declaration", 
        r"(?:中华人民共和国海关出口货物报关单|中華人民共和國海關出口貨物報關單)",
        r"(?:中华人民共和国\s*海[关關]\s*出[口]\s*货[物]\s*报[关關][单單])",
        r"(?:出[口]\s*货[物]\s*报[关關][单單])",
        r"(?i)экспортная\s+декларация", r"(?i)таможенная\s+декларация",  
        r"(?i)ihracat\s+beyannamesi", r"(?i)gümrük\s+beyannamesi",  
        r"(?i)declaración\s+de\s+exportación", r"(?i)declaración\s+aduanera"  
    ],
    DocumentType.PACKING_LIST: [
        r"(?i)packing\s+list",
        r"(?i)упаковочный\s+лист", r"(?i)упаковочная\s+ведомость",  
        r"(?i)paket\s+listesi", r"(?i)paketleme\s+listesi",  
        r"(?i)lista\s+de\s+empaque", r"(?i)lista\s+de\s+embalaje",  
        r"(?:装箱单|裝箱單|包装清单|包裝清單)"  
    ],
    DocumentType.BILL_OF_LANDING: [
        r"(?i)bill\s+of\s+landing", r"(?i)\bB/L\b", r"(?i)\bsea[\s-]*way[\s-]*bill\b",
        r"(?i)коносамент", r"(?i)бортовой\s+коносамент",  
        r"(?i)konşimento", r"(?i)deniz\s+konşimentosu", 
        r"(?i)conocimiento\s+de\s+embarque",  
        r"(?:提单|提單|海运提单|海運提單)"  
    ],
    DocumentType.PRICE_LIST_1: [
        r"(?i)price\s*list",
        r"(?i)прайс[\s-]*лист", r"(?i)прейскурант",  
        r"(?i)fiyat\s+listesi",  
        r"(?i)lista\s+de\s+precios", 
        r"(?:价格表|價格表|价目表|價目表)"  
    ],
    DocumentType.PRICE_LIST_2: [
        r"(?i)price\s*list",
        r"(?i)прайс[\s-]*лист", r"(?i)прейскурант", 
        r"(?i)fiyat\s+listesi", 
        r"(?i)lista\s+de\s+precios", 
        r"(?:价格表|價格表|价目表|價目表)" 
    ],
    DocumentType.QUALITY_CERTIFICATE: [
        r"(?i)quality\s+certificate",
        r"(?i)сертификат\s+качества", r"(?i)качественный\s+сертификат", 
        r"(?i)kalite\s+sertifikası",  
        r"(?i)certificado\s+de\s+calidad", 
        r"(?:质量证书|質量證書|品质证明|品質證明)" 
    ],
    DocumentType.CERTIFICATE_OF_ORIGIN: [
        r"(?i)certificate\s+of\s+origin",
        r"(?i)сертификат\s+происхождения", r"(?i)сертификат\s+о\s+происхождении", 
        r"(?i)menşei\s+sertifikası", r"(?i)orijin\s+sertifikası", 
        r"(?i)certificado\s+de\s+origen",  
        r"(?:原产地证书|原產地證書|产地证明|產地證明)"  
    ],
    DocumentType.VETERINARY_CERTIFICATE: [
        r"(?i)veterinary\s+certificate",
        r"(?i)ветеринарный\s+сертификат", r"(?i)ветеринарное\s+свидетельство", 
        r"(?i)veteriner\s+sertifikası", 
        r"(?i)certificado\s+veterinario", 
        r"(?:兽医证书|獸醫證書|动物检疫证书|動物檢疫證書)"
    ],
    DocumentType.PROFORMA: [
        r"(?i)\bproforma(?:[\s-]+invoice)?\b",
        r"(?i)проформа\s+счёт", r"(?i)проформа\s+счет", r"(?i)проформа\s+инвойс", 
        r"(?i)proforma\s+fatura",  
        r"(?i)proforma\s+factura",  
        r"(?:形式发票|形式發票|预开发票|預開發票)"  
    ]
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



