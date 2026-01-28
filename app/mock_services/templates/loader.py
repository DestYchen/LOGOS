from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from app.core.enums import DocumentType

_DOC_MAPPING = {
    DocumentType.INVOICE: "invoice.json",
    DocumentType.EXPORT_DECLARATION: "export_declaration.json",
    DocumentType.PACKING_LIST: "packing_list.json",
    DocumentType.BILL_OF_LANDING: "bill_of_landing.json",
    DocumentType.PRICE_LIST_1: "price_list_1.json",
    DocumentType.PRICE_LIST_2: "price_list_2.json",
    DocumentType.QUALITY_CERTIFICATE: "quality_certificate.json",
    DocumentType.CERTIFICATE_OF_ORIGIN: "certificate_of_origin.json",
    DocumentType.VETERINARY_CERTIFICATE: "veterinary_certificate.json",
    DocumentType.PROFORMA: "proforma.json",
    DocumentType.SPECIFICATION: "specification.json",
    # New in docs_json_2
    DocumentType.CMR: "cmr.json",
    DocumentType.CONTRACT: "contract.json",
    DocumentType.FORM_A: "form_a.json",
    DocumentType.EAV: "eav.json",
    DocumentType.CT_3: "ct_3.json",
    DocumentType.T1: "t1.json",
}

# Point loader to the new templates directory
_BASE_DIR = Path(__file__).resolve().parent.parent / "docs_json_2"


def load_template_definition(doc_type: DocumentType) -> Dict[str, Any]:
    file_name = _DOC_MAPPING.get(doc_type)
    if not file_name:
        return {"fields": {}}

    path = _BASE_DIR / file_name
    print(path)

    if not path.exists():
        return {"fields": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"fields": {}}

    fields = deepcopy(data.get("fields", {}))
    _ensure_defaults(fields)

    template: Dict[str, Any] = {"fields": fields}

    products = fields.get("products")
    if isinstance(products, dict):
        sample = next((v for v in products.values() if isinstance(v, dict) and v), None)
        if sample:
            product_template = deepcopy(sample)
            _ensure_defaults(product_template)
            template["product_template"] = product_template
            fields["products"] = {}
    return template


def _ensure_defaults(node: Dict[str, Any]) -> None:
    for key, value in node.items():
        if isinstance(value, dict):
            if "value" in value:
                value.setdefault("bbox", [])
                value.setdefault("token_refs", [])
            else:
                _ensure_defaults(value)



