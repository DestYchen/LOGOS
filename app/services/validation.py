from __future__ import annotations


import operator
import re
import uuid
from dataclasses import dataclass
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentType, ValidationSeverity
from app.core.schema import get_schema
from app.models import Document, FilledField, Validation
from datetime import datetime, date


@dataclass
class ValidationMessage:
    rule_id: str
    severity: ValidationSeverity
    message: str
    refs: List[Dict[str, object]]


@dataclass(frozen=True)
class FieldRef:
    doc_type: str
    field_key: str
    label: Optional[str] = None


@dataclass(frozen=True)
class FieldComparisonRule:
    anchor_doc: str
    target_docs: List[str]


@dataclass(frozen=True)
class DateComparison:
    operator: str
    other: FieldRef
    note: Optional[str] = None


@dataclass(frozen=True)
class DateRule:
    rule_id: str
    description: str
    anchor: FieldRef
    comparisons: List[DateComparison]
    severity: ValidationSeverity = ValidationSeverity.ERROR


@dataclass(frozen=True)
class AnchoredEqualityRule:
    rule_id: str
    description: str
    anchor: FieldRef
    targets: List[FieldRef]
    value_kind: str = "string-casefold"
    severity: ValidationSeverity = ValidationSeverity.ERROR


@dataclass(frozen=True)
class GroupEqualityRule:
    rule_id: str
    description: str
    refs: List[FieldRef]
    value_kind: str = "string-casefold"
    severity: ValidationSeverity = ValidationSeverity.ERROR


@dataclass
class FieldValueRecord:
    document: Document
    field: FilledField
    normalized: Any


@dataclass
class InvalidFieldRecord:
    document: Document
    field: FilledField


def _build_ref(
    *,
    doc_id: uuid.UUID,
    field_key: str,
    value: Optional[str] = None,
    normalized: Optional[Any] = None,
    present: Optional[bool] = None,
    page: Optional[int] = None,
    bbox: Optional[Any] = None,
    token_refs: Optional[Any] = None,
    note: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> Dict[str, Any]:
    ref: Dict[str, Any] = {
        "doc_id": doc_id,
        "field_key": field_key,
    }
    if value is not None:
        ref["value"] = value
    if normalized is not None:
        ref["normalized"] = normalized
    if present is not None:
        ref["present"] = present
    if page is not None:
        ref["page"] = page
    if bbox is not None:
        ref["bbox"] = bbox
    if token_refs is not None:
        ref["token_refs"] = token_refs
    if note is not None:
        ref["note"] = note
    if doc_type is not None:
        ref["doc_type"] = doc_type
    return ref


def _ref_from_field(document: Document, field: Optional[FilledField], *, normalized: Optional[Any] = None, note: Optional[str] = None) -> Dict[str, Any]:
    if field is None:
        return _build_ref(
            doc_id=document.id,
            field_key="",
            value=None,
            normalized=normalized,
            present=False,
            note=note,
        )
    return _build_ref(
        doc_id=document.id,
        field_key=field.field_key,
        value=field.value,
        normalized=normalized,
        present=True,
        page=getattr(field, "page", None),
        bbox=getattr(field, "bbox", None),
        token_refs=getattr(field, "token_refs", None),
        note=note,
    )

def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    # Normalize date/datetime to ISO strings for JSONB
    if isinstance(value, (datetime, date)):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class FieldCollection:
    ref: FieldRef
    records: List[FieldValueRecord]
    missing_docs: List[Document]
    invalid_records: List[InvalidFieldRecord]
    doc_type_missing: bool
    unknown_doc_type: bool


class ValidationContext:
    """Helper that groups filled values by document type and field."""

    def __init__(self, documents: List[Document], fields_by_doc: Dict[uuid.UUID, Dict[str, FilledField]]):
        self._documents = documents
        self._fields_by_doc = fields_by_doc
        self._docs_by_type: Dict[DocumentType, List[Document]] = {}
        for doc in documents:
            self._docs_by_type.setdefault(doc.doc_type, []).append(doc)

    def collect(self, ref: FieldRef, normalizer: Callable[[Optional[str]], Optional[Any]]) -> FieldCollection:
        doc_type_enum = _resolve_doc_type(ref.doc_type)
        if doc_type_enum is None:
            return FieldCollection(
                ref=ref,
                records=[],
                missing_docs=[],
                invalid_records=[],
                doc_type_missing=True,
                unknown_doc_type=True,
            )

        docs = self._docs_by_type.get(doc_type_enum, [])
        if not docs:
            return FieldCollection(
                ref=ref,
                records=[],
                missing_docs=[],
                invalid_records=[],
                doc_type_missing=True,
                unknown_doc_type=False,
            )

        records: List[FieldValueRecord] = []
        missing_docs: List[Document] = []
        invalid_records: List[InvalidFieldRecord] = []

        for doc in docs:
            field = self._fields_by_doc.get(doc.id, {}).get(ref.field_key)
            if field is None or not (field.value and field.value.strip()):
                missing_docs.append(doc)
                continue
            normalized = normalizer(field.value)
            if normalized is None:
                invalid_records.append(InvalidFieldRecord(document=doc, field=field))
                continue
            records.append(FieldValueRecord(document=doc, field=field, normalized=normalized))

        return FieldCollection(
            ref=ref,
            records=records,
            missing_docs=missing_docs,
            invalid_records=invalid_records,
            doc_type_missing=False,
            unknown_doc_type=False,
        )

    @staticmethod
    def doc_label(doc: Document) -> str:
        return _doc_label(doc.doc_type.name)

    @staticmethod
    def field_label(ref: FieldRef) -> str:
        return ref.label or _field_label(ref.field_key)

    @staticmethod
    def doc_type_label(doc_type_name: str) -> str:
        return _doc_label(doc_type_name)


_OPERATOR_FUNC = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


_OPERATOR_TEXT = {
    "<": "earlier than",
    "<=": "earlier than or equal to",
    ">": "later than",
    ">=": "later than or equal to",
    "==": "equal to",
}


def _resolve_doc_type(name: str) -> Optional[DocumentType]:
    return DocumentType.__members__.get(name)


def _humanize_identifier(identifier: str) -> str:
    return identifier.replace("_", " ").title()


def _doc_label(doc_type_name: str) -> str:
    return _humanize_identifier(doc_type_name)


# -------------------- Products comparison helpers --------------------

def _collapse_spaces(value: str) -> str:
    return " ".join(value.split())


def _normalize_name_for_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    # Case-insensitive comparison, preserve all symbols otherwise
    return _collapse_spaces(trimmed).casefold()


def _normalize_weight_for_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


def _normalize_size_for_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


def _product_key(name: Optional[str], latin: Optional[str], size: Optional[str]):
    name_k = _normalize_name_for_key(name)
    latin_k = _normalize_name_for_key(latin)
    size_k = _normalize_size_for_key(size)

    if not name_k:
        return None  # cannot identify row without name
    if latin_k is None and size_k is None:
        # Minimal key contains just name when others are missing
        return (name_k,)
    if latin_k is None:
        return (name_k, size_k)
    if size_k is None:
        return (name_k, latin_k)
    return (name_k, latin_k, size_k)


def _collect_product_rows_for_doc(doc_fields: Dict[str, FilledField]) -> List[Dict[str, Optional[str]]]:
    """Group flattened fields into product rows.

    Expects keys like 'products.product_1.name_product'.
    Returns list of row dicts containing raw values per product.
    """
    grouped: Dict[str, Dict[str, Optional[str]]] = defaultdict(dict)
    for key, field in doc_fields.items():
        if not key.startswith("products."):
            continue
        parts = key.split(".")
        if len(parts) < 3:
            continue
        # parts[1] is product identifier; ignore template artifacts
        prod_id = parts[1]
        if prod_id == "product_template":
            continue
        sub_key = ".".join(parts[2:])
        grouped[prod_id][sub_key] = field.value
        grouped[prod_id]["__id"] = prod_id  # keep original product_* id for refs
    return [grouped[k] for k in sorted(grouped.keys())]


def _build_product_multiset(rows: List[Dict[str, Optional[str]]]) -> Tuple[Counter, Dict[tuple, List[Dict[str, Optional[str]]]]]:
    counter: Counter = Counter()
    buckets: Dict[tuple, List[Dict[str, Optional[str]]]] = defaultdict(list)
    for row in rows:
        name = row.get("name_product")
        latin = row.get("latin_name")
        size = row.get("size_product")
        key = _product_key(name, latin, size)
        if key is None:
            # skip unidentifiable rows; higher-level rules may report missing name
            continue
        counter[key] += 1
        buckets[key].append(row)
    return counter, buckets


def _prefer_anchor(documents: List[Document], rows_by_doc: Dict[uuid.UUID, List[Dict[str, Optional[str]]]]) -> Optional[Document]:
    # Prefer INVOICE, then PROFORMA; otherwise the doc with most rows
    preferred_order = [DocumentType.INVOICE, DocumentType.PROFORMA]
    by_type = {doc.doc_type: doc for doc in documents}
    for dt in preferred_order:
        if dt in by_type and rows_by_doc.get(by_type[dt].id):
            return by_type[dt]
    # fallback: doc with max rows
    best_doc = None
    best_count = -1
    for doc in documents:
        count = len(rows_by_doc.get(doc.id, []))
        if count > best_count:
            best_doc = doc
            best_count = count
    return best_doc


def _compare_products(
    anchor_doc: Document,
    target_doc: Document,
    rows_by_doc: Dict[uuid.UUID, List[Dict[str, Optional[str]]]],
    validations: List[ValidationMessage],
) -> None:
    anchor_rows = rows_by_doc.get(anchor_doc.id, [])
    target_rows = rows_by_doc.get(target_doc.id, [])

    anchor_ms, anchor_buckets = _build_product_multiset(anchor_rows)
    target_ms, target_buckets = _build_product_multiset(target_rows)

    # Normalizer used across all product comparisons
    def _value_for_compare(field_key: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if field_key in ("name_product", "latin_name"):
            return _normalize_name_for_key(value)
        return value.strip()

    # Missing in target
    for key, cnt in anchor_ms.items():
        delta = cnt - target_ms.get(key, 0)
        if delta > 0:
            # Collect detailed refs for missing rows from anchor
            start_idx = target_ms.get(key, 0)
            detailed_refs: List[Dict[str, Any]] = []
            PRODUCT_COMPARE_FIELDS = [
                "name_product",
                "latin_name",
                "net_weight",
                "size_product",
                "unit_box",
                "packages",
                "gross_weight",
                "price_per_unit",
                "total_price",
                "commodity_code",
            ]
            for idx in range(start_idx, cnt):
                row_a = anchor_buckets[key][idx]
                prod_id_a = row_a.get("__id", "?")
                for fkey in PRODUCT_COMPARE_FIELDS:
                    if fkey in row_a and row_a.get(fkey) is not None:
                        val = row_a.get(fkey)
                        norm = _value_for_compare(fkey, val)
                        detailed_refs.append(
                            _build_ref(
                                doc_id=anchor_doc.id,
                                field_key=f"products.{prod_id_a}.{fkey}",
                                value=val,
                                normalized=norm,
                                present=True,
                            )
                        )
            # Add summary ref for target products node with a note
            detailed_refs.append(
                _build_ref(doc_id=target_doc.id, field_key="products", note="missing_rows")
            )
            validations.append(
                ValidationMessage(
                    rule_id=f"products_missing_in_{target_doc.doc_type.name}",
                    severity=ValidationSeverity.ERROR,
                    message=f"{delta} product(s) missing in {target_doc.doc_type.name} compared to {anchor_doc.doc_type.name}",
                    refs=detailed_refs,
                )
            )

    # Extra in target
    for key, cnt in target_ms.items():
        delta = cnt - anchor_ms.get(key, 0)
        if delta > 0:
            # Detailed refs for extra rows from target
            start_idx = anchor_ms.get(key, 0)
            detailed_refs: List[Dict[str, Any]] = []
            PRODUCT_COMPARE_FIELDS = [
                "name_product",
                "latin_name",
                "net_weight",
                "size_product",
                "unit_box",
                "packages",
                "gross_weight",
                "price_per_unit",
                "total_price",
                "commodity_code",
            ]
            for idx in range(start_idx, cnt):
                row_b = target_buckets[key][idx]
                prod_id_b = row_b.get("__id", "?")
                for fkey in PRODUCT_COMPARE_FIELDS:
                    if fkey in row_b and row_b.get(fkey) is not None:
                        val = row_b.get(fkey)
                        norm = _value_for_compare(fkey, val)
                        detailed_refs.append(
                            _build_ref(
                                doc_id=target_doc.id,
                                field_key=f"products.{prod_id_b}.{fkey}",
                                value=val,
                                normalized=norm,
                                present=True,
                            )
                        )
            detailed_refs.append(
                _build_ref(doc_id=target_doc.id, field_key="products", note="extra_rows")
            )
            validations.append(
                ValidationMessage(
                    rule_id=f"products_extra_in_{target_doc.doc_type.name}",
                    severity=ValidationSeverity.WARN,
                    message=f"{delta} extra product(s) in {target_doc.doc_type.name} versus {anchor_doc.doc_type.name}",
                    refs=detailed_refs,
            )
        )

    # Count mismatch where both have entries
    for key in set(anchor_ms.keys()).intersection(set(target_ms.keys())):
        a, b = anchor_ms[key], target_ms[key]
        if a != b:
            detailed_refs: List[Dict[str, Any]] = []
            # Include context for existing paired rows
            pairs = min(a, b)
            for idx in range(pairs):
                row_a = anchor_buckets[key][idx]
                row_b = target_buckets[key][idx]
                prod_id_a = row_a.get("__id", "?")
                prod_id_b = row_b.get("__id", "?")
                for fkey in [
                    "name_product",
                    "latin_name",
                    "net_weight",
                    "size_product",
                    "unit_box",
                    "packages",
                    "gross_weight",
                    "price_per_unit",
                    "total_price",
                    "commodity_code",
                ]:
                    vala = row_a.get(fkey)
                    valb = row_b.get(fkey)
                    if vala is not None:
                        detailed_refs.append(
                            _build_ref(
                                doc_id=anchor_doc.id,
                                field_key=f"products.{prod_id_a}.{fkey}",
                                value=vala,
                                normalized=_value_for_compare(fkey, vala),
                                present=True,
                            )
                        )
                    if valb is not None:
                        detailed_refs.append(
                            _build_ref(
                                doc_id=target_doc.id,
                                field_key=f"products.{prod_id_b}.{fkey}",
                                value=valb,
                                normalized=_value_for_compare(fkey, valb),
                                present=True,
                            )
                        )
            # Summary refs for counts
            detailed_refs.append(_build_ref(doc_id=anchor_doc.id, field_key="products", note=f"count={a}"))
            detailed_refs.append(_build_ref(doc_id=target_doc.id, field_key="products", note=f"count={b}"))
            validations.append(
                ValidationMessage(
                    rule_id=f"products_count_mismatch_{target_doc.doc_type.name}",
                    severity=ValidationSeverity.WARN,
                    message=f"Product count for a matched key differs: {a} vs {b}",
                    refs=detailed_refs,
                )
            )

    # Detailed field comparison for matched pairs
    PRODUCT_COMPARE_FIELDS = [
        "name_product",
        "latin_name",
        "net_weight",
        "size_product",
        "unit_box",
        "packages",
        "gross_weight",
        "price_per_unit",
        "total_price",
        "commodity_code",
    ]


    for key in set(anchor_ms.keys()).intersection(set(target_ms.keys())):
        pairs = min(anchor_ms[key], target_ms[key])
        for idx in range(pairs):
            row_a = anchor_buckets[key][idx]
            row_b = target_buckets[key][idx]
            prod_id_a = row_a.get("__id", "?")
            prod_id_b = row_b.get("__id", "?")
            for fkey in PRODUCT_COMPARE_FIELDS:
                av = row_a.get(fkey)
                bv = row_b.get(fkey)
                if av is None or bv is None:
                    continue
                va = _value_for_compare(fkey, av)
                vb = _value_for_compare(fkey, bv)
                if va != vb:
                    validations.append(
                        ValidationMessage(
                            rule_id=f"product_field_mismatch_{fkey}",
                            severity=ValidationSeverity.WARN,
                            message=(
                                f"Field '{fkey}' differs between {anchor_doc.doc_type.name} and {target_doc.doc_type.name}"
                            ),
                            refs=[
                                _build_ref(
                                    doc_id=anchor_doc.id,
                                    field_key=f"products.{prod_id_a}.{fkey}",
                                    value=av,
                                    normalized=va,
                                    present=True,
                                ),
                                _build_ref(
                                    doc_id=target_doc.id,
                                    field_key=f"products.{prod_id_b}.{fkey}",
                                    value=bv,
                                    normalized=vb,
                                    present=True,
                                ),
                            ],
                        )
                    )


def _field_label(field_key: str) -> str:
    return _humanize_identifier(field_key)


def _normalize_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _normalize_string_casefold(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_string(value)
    if normalized is None:
        return None
    return normalized.casefold()


def _normalize_number(value: Optional[str]) -> Optional[float]:
    return _parse_number(value)


def _normalize_date(value: Optional[str]):
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "")).date()
    except ValueError:
        pass
    formats = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y.%m.%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_value(value: Optional[str], kind: str) -> Optional[Any]:
    if kind == "number":
        return _normalize_number(value)
    if kind == "string":
        return _normalize_string(value)
    if kind == "string-upper":
        normalized = _normalize_string(value)
        return normalized.upper() if normalized else None
    # default string handling uses casefold for robustness
    return _normalize_string_casefold(value)


def _ref(doc_type: str, field_key: str, label: Optional[str] = None) -> FieldRef:
    return FieldRef(doc_type=doc_type, field_key=field_key, label=label)


def _refs(doc_types: Iterable[str], field_key: str, *, exclude: Optional[Iterable[str]] = None, label: Optional[str] = None) -> List[FieldRef]:
    exclude_set = {item.upper() for item in exclude} if exclude else set()
    refs: List[FieldRef] = []
    for doc_type in doc_types:
        if doc_type.upper() in exclude_set:
            continue
        refs.append(_ref(doc_type, field_key, label))
    return refs


ALL_DOC_TYPES = [
    "PROFORMA",
    "INVOICE",
    "PACKING_LIST",
    "BILL_OF_LANDING",
    "PRICE_LIST_1",
    "PRICE_LIST_2",
    "QUALITY_CERTIFICATE",
    "VETERINARY_CERTIFICATE",
    "CERTIFICATE_OF_ORIGIN",
    "EXPORT_DECLARATION",
    "SPECIFICATION",
    "CMR",
    "FORM_A",
    "EAV",
    "CT_3",
]

FIELD_MATRIX_DOC_TYPES = [
    "CONTRACT",
    "ADDENDUM",
    "PROFORMA",
    "INVOICE",
    "BILL_OF_LADING",
    "CMR",
    "PACKING_LIST",
    "PRICE_LIST_1",
    "PRICE_LIST_2",
    "QUALITY_CERTIFICATE",
    "VETERINARY_CERTIFICATE",
    "EXPORT_DECLARATION",
    "SPECIFICATION",
    "CERTIFICATE_OF_ORIGIN",
    "FORM_A",
    "EAV",
    "CT-3",
]

FIELD_MATRIX_DOC_TYPE_MAP = {
    "CONTRACT": "CONTRACT",
    "ADDENDUM": None,  # placeholder for future support
    "PROFORMA": "PROFORMA",
    "INVOICE": "INVOICE",
    "BILL_OF_LADING": "BILL_OF_LANDING",
    "CMR": "CMR",
    "PACKING_LIST": "PACKING_LIST",
    "PRICE_LIST_1": "PRICE_LIST_1",
    "PRICE_LIST_2": "PRICE_LIST_2",
    "QUALITY_CERTIFICATE": "QUALITY_CERTIFICATE",
    "VETERINARY_CERTIFICATE": "VETERINARY_CERTIFICATE",
    "EXPORT_DECLARATION": "EXPORT_DECLARATION",
    "SPECIFICATION": "SPECIFICATION",
    "CERTIFICATE_OF_ORIGIN": "CERTIFICATE_OF_ORIGIN",
    "FORM_A": "FORM_A",
    "EAV": "EAV",
    "CT-3": "CT-3",
}

FIELD_MATRIX_FIELDS: List[Tuple[str, List[str]]] = [
    ("proforma_date", ["proforma_date"]),
    ("proforma_no", ["proforma_no"]),
    ("invoice_date", ["invoice_date"]),
    ("invoice_no", ["invoice_no"]),
    ("country_of_origin", ["country_of_origin"]),
    ("producer", ["producer"]),
    ("buyer", ["buyer"]),
    ("seller", ["seller"]),
    ("exporter", ["exporter"]),
    ("importer", ["importer"]),
    ("incoterms", ["incoterms"]),
    ("terms_of_payment", ["terms_of_payment"]),
    ("bank_details", ["bank_details"]),
    ("total_price", ["total_price"]),
    ("destination", ["destination"]),
    ("vessel", ["vessel"]),
    ("container_no", ["container_no"]),
    ("veterinary_seal", ["veterinary_seal"]),
    ("linear_seal", ["linear_seal"]),
    ("veterinary_certificate_no", ["veterinary_certificate_no"]),
    ("veterinary_certificate_date", ["veterinary_certificate_date"]),
    ("HS_code", ["HS_code", "commodity_code"]),
]

DOCUMENT_NUMBER_FIELDS: Dict[str, List[str]] = {
    "CONTRACT": ["contract_no"],
    "PROFORMA": ["proforma_no"],
    "INVOICE": ["invoice_no"],
    "BILL_OF_LANDING": ["bill_of_landing_number"],
    "EXPORT_DECLARATION": ["export_declaration_no"],
    "CERTIFICATE_OF_ORIGIN": ["certificate_of_origin_no"],
    "VETERINARY_CERTIFICATE": ["veterinary_certificate_no"],
    "FORM_A": ["form_a_no"],
    "EAV": ["eav_no"],
    "CT-3": ["ct3_no"],
}

DOCUMENT_DATE_FIELDS: Dict[str, List[str]] = {
    "CONTRACT": ["contract_date"],
    "PROFORMA": ["proforma_date"],
    "INVOICE": ["invoice_date"],
    "BILL_OF_LANDING": ["bill_of_landing_date"],
    "CMR": ["cmr_date"],
    "PACKING_LIST": ["packing_list_date"],
    "PRICE_LIST_1": ["price_list_1_date"],
    "PRICE_LIST_2": ["price_list_2_date"],
    "QUALITY_CERTIFICATE": ["quality_certificate_date"],
    "VETERINARY_CERTIFICATE": ["veterinary_certificate_date"],
    "EXPORT_DECLARATION": ["export_declaration_date"],
    "SPECIFICATION": ["specification_date"],
    "CERTIFICATE_OF_ORIGIN": ["certificate_of_origin_date"],
    "FORM_A": ["form_a_date"],
    "EAV": ["eav_date"],
    "CT-3": ["ct3_date"],
}

FIELD_COMPARISON_RULES: Dict[str, List[FieldComparisonRule]] = defaultdict(list)


# Date field references
PROFORMA_DATE = _ref("PROFORMA", "proforma_date", "Proforma date")
INVOICE_DATE = _ref("INVOICE", "invoice_date", "Invoice date")
BOL_DATE = _ref("BILL_OF_LANDING", "bill_of_landing_date", "Bill of landing date")
PACKING_LIST_DATE = _ref("PACKING_LIST", "packing_list_date", "Packing list date")
PRICE_LIST1_DATE = _ref("PRICE_LIST_1", "price_list_1_date", "Price list 1 date")
PRICE_LIST2_DATE = _ref("PRICE_LIST_2", "price_list_2_date", "Price list 2 date")
QUALITY_CERT_DATE = _ref("QUALITY_CERTIFICATE", "quality_certificate_date", "Quality certificate date")
VET_CERT_DATE = _ref("VETERINARY_CERTIFICATE", "veterinary_certificate_date", "Veterinary certificate date")
EXPORT_DECL_DATE = _ref("EXPORT_DECLARATION", "export_declaration_date", "Export declaration date")
SPECIFICATION_DATE = _ref("SPECIFICATION", "specification_date", "Specification date")
CERT_ORIGIN_DATE = _ref("CERTIFICATE_OF_ORIGIN", "certificate_of_origin_date", "Certificate of origin date")
CMR_DATE = _ref("CMR", "cmr_date", "CMR date")
FORM_A_DATE = _ref("FORM_A", "form_a_date", "FORM A date")
EAV_DATE = _ref("EAV", "eav_date", "EAV date")


DATE_RULES: List[DateRule] = [
    DateRule(
        rule_id="date_proforma_earliest",
        description="Дата проформы должна быть самой ранней среди связанных документов",
        anchor=PROFORMA_DATE,
        comparisons=[
            DateComparison("<=", INVOICE_DATE),
            DateComparison("<=", BOL_DATE),
            DateComparison("<=", PACKING_LIST_DATE),
            DateComparison("<=", PRICE_LIST1_DATE),
            DateComparison("<=", PRICE_LIST2_DATE),
            DateComparison("<=", QUALITY_CERT_DATE),
            DateComparison("<=", VET_CERT_DATE),
            DateComparison("<=", EXPORT_DECL_DATE),
            DateComparison("<=", SPECIFICATION_DATE),
            DateComparison("<=", CERT_ORIGIN_DATE),
            DateComparison("<=", CMR_DATE),
            DateComparison("<=", FORM_A_DATE),
            DateComparison("<=", EAV_DATE),
        ],
    ),
    DateRule(
        rule_id="date_invoice_not_too_early",
        description="Дата инвойса не должна быть раньше даты отгрузки и даты сертификатов",
        anchor=INVOICE_DATE,
        comparisons=[
            DateComparison(">=", BOL_DATE),
            DateComparison(">=", PACKING_LIST_DATE),
            DateComparison(">=", QUALITY_CERT_DATE),
            DateComparison(">=", VET_CERT_DATE),
            DateComparison(">=", EXPORT_DECL_DATE),
            DateComparison(">=", SPECIFICATION_DATE),
            DateComparison(">=", CERT_ORIGIN_DATE),
            DateComparison(">=", CMR_DATE),
            DateComparison(">=", FORM_A_DATE),
            DateComparison(">=", EAV_DATE),
        ],
    ),
    DateRule(
        rule_id="date_bill_of_landing_after_sources",
        description="Дата коноссамента должна быть позже дат проформы, инвойса и прайс листов",
        anchor=BOL_DATE,
        comparisons=[
            DateComparison(">=", PROFORMA_DATE),
            DateComparison(">=", INVOICE_DATE),
            DateComparison(">=", PRICE_LIST1_DATE),
            DateComparison(">=", PRICE_LIST2_DATE),
        ],
    ),
    DateRule(
        rule_id="date_cmr_after_sources",
        description="Дата CMR должна быть позже даты инвойса, позже проформы и прайс-листа 1",
        anchor=CMR_DATE,
        comparisons=[
            DateComparison(">=", INVOICE_DATE),
            DateComparison(">", PROFORMA_DATE),
            DateComparison(">", PRICE_LIST1_DATE),
        ],
    ),
    DateRule(
        rule_id="date_packing_list_before_ship",
        description="Дата пакинг листа должна быть раньше чем дата коносамента и не позже чем дата инвойса",
        anchor=PACKING_LIST_DATE,
        comparisons=[
            DateComparison("<", BOL_DATE),
            DateComparison("<=", INVOICE_DATE),
        ],
    ),
    DateRule(
        rule_id="date_price_list_1_before_proforma",
        description="Дата прайс листа 1 должна быть раньше или равна дате проформы",
        anchor=PRICE_LIST1_DATE,
        comparisons=[DateComparison("<=", PROFORMA_DATE)],
    ),
    DateRule(
        rule_id="date_price_list_2_between_proforma_invoice",
        description="Дата прайс листа 2 должна быть позже даты профомы и не позжедаты инвойса",
        anchor=PRICE_LIST2_DATE,
        comparisons=[
            DateComparison(">", PROFORMA_DATE),
            DateComparison("<=", INVOICE_DATE),
        ],
    ),
    DateRule(
        rule_id="date_quality_certificate_after_bol",
        description="Дата сертификатат качества должна быть позже или равна дате коноссамента",
        anchor=QUALITY_CERT_DATE,
        comparisons=[
            DateComparison(">=", BOL_DATE),
            DateComparison(">=", CMR_DATE),
        ],
    ),
    DateRule(
        rule_id="date_veterinary_certificate_before_bol",
        description="Дата ветеринарного сертификата должна быть раньше чем дата коноссамента",
        anchor=VET_CERT_DATE,
        comparisons=[
            DateComparison("<", BOL_DATE),
            DateComparison("==", CMR_DATE),
        ],
    ),
    DateRule(
        rule_id="date_export_declaration_after_bol",
        description="Дата экспортной декларации должна быть позже или равна даты коноссамента",
        anchor=EXPORT_DECL_DATE,
        comparisons=[
            DateComparison(">=", BOL_DATE),
            DateComparison(">=", CMR_DATE),
        ],
    ),
    DateRule(
        rule_id="date_specification_not_after_invoice",
        description="Дата спецификации должна быть не позже, чем дата инвойса",
        anchor=SPECIFICATION_DATE,
        comparisons=[DateComparison("<=", INVOICE_DATE)],
    ),
    DateRule(
        rule_id="date_certificate_origin_after_invoice",
        description="Дата сертификата происхождения должна быть позже или равно дате инвойса",
        anchor=CERT_ORIGIN_DATE,
        comparisons=[DateComparison(">=", INVOICE_DATE)],
    ),
    DateRule(
        rule_id="date_form_a_after_invoice",
        description="Дата FORM A должна быть равна или позже даты инвойса",
        anchor=FORM_A_DATE,
        comparisons=[DateComparison(">=", INVOICE_DATE)],
    ),
    DateRule(
        rule_id="date_eav_after_invoice",
        description="Дата EAV должна быть равна или позже даты инвойса",
        anchor=EAV_DATE,
        comparisons=[DateComparison(">=", INVOICE_DATE)],
    ),
]


ANCHORED_EQUALITY_RULES: List[AnchoredEqualityRule] = [
    AnchoredEqualityRule(
        rule_id="contract_no_alignment",
        description="Номер контракта должен совпадать во всех связанных документах",
        anchor=_ref("CONTRACT", "contract_no", "Contract number"),
        targets=[
            _ref("PROFORMA", "contract_no"),
            _ref("INVOICE", "contract_no"),
            _ref("SPECIFICATION", "contract_no"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="additional_agreements_alignment",
        description="Дополнительные соглашения должны совпадать во всех связанных документах",
        anchor=_ref("CONTRACT", "additional_agreements", "Additional agreements"),
        targets=[
            _ref("PROFORMA", "additional_agreements"),
            _ref("INVOICE", "additional_agreements"),
            _ref("SPECIFICATION", "additional_agreements"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="country_of_origin_consistency",
        description="Страна происхождения в ветеринарном сертификате должна совпадать с другими документами",
        anchor=_ref("VETERINARY_CERTIFICATE", "country_of_origin", "Country of origin"),
        targets=_refs(ALL_DOC_TYPES, "country_of_origin", exclude=["VETERINARY_CERTIFICATE"]),
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="total_price_consistency",
        description="Общая стоимость в инвойсе должна совпадать с другими документами",
        anchor=_ref("INVOICE", "total_price", "Total price"),
        targets=[
            _ref("CONTRACT", "total_price"),
            _ref("PROFORMA", "total_price"),
            _ref("SPECIFICATION", "total_price"),
            _ref("EXPORT_DECLARATION", "total_price"),
        ],
        value_kind="string",
    ),
    AnchoredEqualityRule(
        rule_id="producer_consistency",
        description="Производитель в ветеринарном сертификате должен совпадать с другими документами",
        anchor=_ref("VETERINARY_CERTIFICATE", "producer", "Producer"),
        targets=[
            _ref("INVOICE", "producer"),
            _ref("PACKING_LIST", "producer"),
            _ref("PRICE_LIST_1", "producer"),
            _ref("PRICE_LIST_2", "producer"),
            _ref("QUALITY_CERTIFICATE", "producer"),
            _ref("CERTIFICATE_OF_ORIGIN", "producer"),
        ],
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="incoterms_consistency",
        description="Условия доставки из инвойса должны совпадать с другими документами",
        anchor=_ref("INVOICE", "incoterms", "Incoterms"),
        targets=[
            _ref("CONTRACT", "incoterms"),
            _ref("PROFORMA", "incoterms"),
            _ref("PRICE_LIST_1", "incoterms"),
            _ref("PRICE_LIST_2", "incoterms"),
            _ref("EXPORT_DECLARATION", "incoterms"),
            _ref("SPECIFICATION", "incoterms"),
            _ref("CMR", "incoterms"),
        ],
        value_kind="string-upper",
    ),
    AnchoredEqualityRule(
        rule_id="terms_of_payment_consistency",
        description="Условия оплаты из инвойса должны совпадать с другими документами",
        anchor=_ref("INVOICE", "terms_of_payment", "Terms of payment"),
        targets=[
            _ref("CONTRACT", "terms_of_payment"),
            _ref("PROFORMA", "terms_of_payment"),
            _ref("SPECIFICATION", "terms_of_payment"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="bank_details_consistency",
        description="Банковские реквизиты в контракте должны совпадать с инвойсом и проформой",
        anchor=_ref("CONTRACT", "bank_details", "Bank details"),
        targets=[
            _ref("INVOICE", "bank_details"),
            _ref("PROFORMA", "bank_details"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="exporter_consistency",
        description="Экспортер в ветеринарном сертификате должен совпадать с другими",
        anchor=_ref("VETERINARY_CERTIFICATE", "exporter", "Exporter"),
        targets=[
            _ref("BILL_OF_LANDING", "exporter"),
            _ref("CERTIFICATE_OF_ORIGIN", "exporter"),
            _ref("CMR", "exporter"),
            _ref("FORM_A", "exporter"),
            _ref("EAV", "exporter"),
            _ref("CT_3", "exporter"),
        ],
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="recipient_matches_contract_buyer",
        description="Получатель из контракта должен совпадать с импортёрами в транспортных документах",
        anchor=_ref("CONTRACT", "buyer", "Contract buyer"),
        targets=[
            _ref("BILL_OF_LANDING", "importer"),
            _ref("CMR", "importer"),
            _ref("CERTIFICATE_OF_ORIGIN", "importer"),
            _ref("FORM_A", "importer"),
            _ref("EAV", "importer"),
            _ref("CT_3", "importer"),
        ],
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="proforma_number_consistency",
        description="Номер проформы должен совпадать в инвойсе и экспортной декларации",
        anchor=_ref("PROFORMA", "proforma_no", "Proforma number"),
        targets=[
            _ref("INVOICE", "proforma_no"),
            _ref("EXPORT_DECLARATION", "proforma_no"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="invoice_number_consistency",
        description="Номер инвойса должен совпадать с другими документами",
        anchor=_ref("INVOICE", "invoice_no", "Invoice number"),
        targets=[
            _ref("PACKING_LIST", "invoice_no"),
            _ref("EXPORT_DECLARATION", "invoice_no"),
            _ref("CERTIFICATE_OF_ORIGIN", "invoice_no"),
            _ref("CMR", "invoice_no"),
            _ref("FORM_A", "invoice_no"),
            _ref("EAV", "invoice_no"),
            _ref("CT_3", "invoice_no"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="veterinary_seal_consistency",
        description="Ветеринарная пломба в ветеринарном сертификате должна совпадать с другими документами",
        anchor=_ref("VETERINARY_CERTIFICATE", "veterinary_seal", "Veterinary seal"),
        targets=[
            _ref("BILL_OF_LANDING", "veterinary_seal"),
            _ref("QUALITY_CERTIFICATE", "veterinary_seal"),
            _ref("CERTIFICATE_OF_ORIGIN", "veterinary_seal"),
            _ref("PACKING_LIST", "veterinary_seal"),
            _ref("CMR", "veterinary_seal"),
            _ref("FORM_A", "veterinary_seal"),
            _ref("EAV", "veterinary_seal"),
            _ref("CT_3", "veterinary_seal"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="linear_seal_consistency",
        description="Линейная прлобма в коноссаменте должна совпадать с другими документами",
        anchor=_ref("BILL_OF_LANDING", "linear_seal", "Linear seal"),
        targets=[
            _ref("QUALITY_CERTIFICATE", "linear_seal"),
            _ref("CERTIFICATE_OF_ORIGIN", "linear_seal"),
            _ref("PACKING_LIST", "linear_seal"),
            _ref("FORM_A", "linear_seal"),
            _ref("EAV", "linear_seal"),
            _ref("CT_3", "linear_seal"),
        ],
    ),
    # AnchoredEqualityRule(
    #     rule_id="name_product_consistency",
    #     description="Наименование продукта должно совпадать с другими документами",
    #     anchor=_ref("INVOICE", "name_product", "Product name"),
    #     targets=_refs(ALL_DOC_TYPES, "name_product", exclude=["INVOICE"]),
    # ),
    # AnchoredEqualityRule(
    #     rule_id="latin_name_consistency",
    #     description="Латинское наименование в ветеринарном сертификате должно совпадать с другими документами",
    #     anchor=_ref("VETERINARY_CERTIFICATE", "latin_name", "Latin name"),
    #     targets=_refs(ALL_DOC_TYPES, "latin_name", exclude=["VETERINARY_CERTIFICATE"]),
    # ),
    # AnchoredEqualityRule(
    #     rule_id="commodity_code_consistency",
    #     description="Commodity code must match the invoice across documents",
    #     anchor=_ref("INVOICE", "commodity_code", "Commodity code"),
    #     targets=_refs(ALL_DOC_TYPES, "commodity_code", exclude=["INVOICE"]),
    # ),
]


GROUP_EQUALITY_RULES: List[GroupEqualityRule] = [
    GroupEqualityRule(
        rule_id="buyer_alignment",
        description="Покупатель должен быть одинаковый среди проформы, инвойса, экспортной декларации, спецификации, ветеринарного сертификата и серфтификата происхождения",
        refs=[
            _ref("CONTRACT", "buyer"),
            _ref("PROFORMA", "buyer"),
            _ref("INVOICE", "buyer"),
            _ref("EXPORT_DECLARATION", "buyer"),
            _ref("SPECIFICATION", "buyer"),
            _ref("VETERINARY_CERTIFICATE", "buyer"),
            _ref("CERTIFICATE_OF_ORIGIN", "buyer"),
            _ref("PACKING_LIST", "buyer"),
        ],
    ),
    GroupEqualityRule(
        rule_id="seller_alignment",
        description="Seller must be identical across Proforma, Invoice, Export declaration, Specification and price lists" \
        "Продавец должен быть одинаковый среди проформы, инвойса, экспортной декларации, спецификации и прайс листов",
        refs=[
            _ref("CONTRACT", "seller"),
            _ref("PROFORMA", "seller"),
            _ref("INVOICE", "seller"),
            _ref("EXPORT_DECLARATION", "seller"),
            _ref("SPECIFICATION", "seller"),
            _ref("PRICE_LIST_1", "seller"),
            _ref("PRICE_LIST_2", "seller"),
        ],
    ),
    GroupEqualityRule(
        rule_id="container_number_alignment",
        description="Номер контейнера должен быть одинаковый среди инвойса, ветеринарного сертификата, сертификата качества, серфтификата происхождения и коноссамента",
        refs=[
            _ref("INVOICE", "container_no"),
            _ref("VETERINARY_CERTIFICATE", "container_no"),
            _ref("QUALITY_CERTIFICATE", "container_no"),
            _ref("CERTIFICATE_OF_ORIGIN", "container_no"),
            _ref("BILL_OF_LANDING", "container_no"),
            _ref("CMR", "container_no"),
            _ref("FORM_A", "container_no"),
            _ref("EAV", "container_no"),
            _ref("CT_3", "container_no"),
        ],
    ),
    GroupEqualityRule(
        rule_id="vessel_alignment",
        description="Транспорт доставки должен быть одинаковый среди инвойса, ветеринарного сертификата, серфтификата качества и коноссамента",
        refs=[
            _ref("INVOICE", "vessel"),
            _ref("VETERINARY_CERTIFICATE", "vessel"),
            _ref("QUALITY_CERTIFICATE", "vessel"),
            _ref("CERTIFICATE_OF_ORIGIN", "vessel"),
            _ref("BILL_OF_LANDING", "vessel"),
        ],
    ),
    GroupEqualityRule(
        rule_id="importer_alignment",
        description="Импортер должен быть одинаковым у коноссамента и сертификата происхождения",
        refs=[
            _ref("BILL_OF_LANDING", "importer"),
            _ref("CERTIFICATE_OF_ORIGIN", "importer"),
            _ref("CMR", "importer"),
            _ref("FORM_A", "importer"),
            _ref("EAV", "importer"),
            _ref("CT_3", "importer"),
        ],
    ),
]


def _register_field_comparison_rules() -> None:
    for rule in ANCHORED_EQUALITY_RULES:
        anchor_field = rule.anchor.field_key
        anchor_doc = rule.anchor.doc_type
        targets = [ref.doc_type for ref in rule.targets if ref.doc_type]
        if anchor_field and anchor_doc and targets:
            FIELD_COMPARISON_RULES[anchor_field].append(FieldComparisonRule(anchor_doc, targets))
    for rule in GROUP_EQUALITY_RULES:
        if not rule.refs:
            continue
        anchor = rule.refs[0]
        targets = [ref.doc_type for ref in rule.refs[1:] if ref.doc_type]
        if anchor.field_key and anchor.doc_type and targets:
            FIELD_COMPARISON_RULES[anchor.field_key].append(FieldComparisonRule(anchor.doc_type, targets))


_register_field_comparison_rules()
# Product-level group equality checks disabled (handled by per-product matcher)


def _collect_records_for_rule(
    context: ValidationContext,
    ref: FieldRef,
    value_kind: str,
    rule_id: str,
    description: str,
    validations: List[ValidationMessage],
    missing_severity: ValidationSeverity = ValidationSeverity.WARN,
) -> List[FieldValueRecord]:
    normalizer: Callable[[Optional[str]], Optional[Any]]
    if value_kind == "date":
        normalizer = _normalize_date
    else:
        normalizer = lambda value: _normalize_value(value, value_kind)

    collection = context.collect(ref, normalizer)

    def add(message: str, refs: List[Dict[str, object]]) -> None:
        validations.append(
            ValidationMessage(
                rule_id=f"{rule_id}_availability",
                severity=missing_severity,
                message=message,
                refs=refs,
            )
        )

    if collection.unknown_doc_type:
        # Emit placeholder ref for unknown doc type
        add(
            f"{description}: document type '{ref.doc_type}' is not defined in the system",
            [
                _build_ref(
                    doc_id=uuid.UUID(int=0),
                    field_key=ref.field_key,
                    value=None,
                    normalized=None,
                    present=False,
                    note="unknown_doc_type",
                )
            ],
        )
        return []

    if collection.doc_type_missing:
        # Placeholder ref for missing document type
        add(
            f"{description}: documents of type {_doc_label(ref.doc_type)} are missing in the batch",
            [
                _build_ref(
                    doc_id=uuid.UUID(int=0),
                    field_key=ref.field_key,
                    value=None,
                    normalized=None,
                    present=False,
                    note="missing_doc_type",
                )
            ],
        )

    for doc in collection.missing_docs:
        add(
            f"{description}: field {context.field_label(ref)} missing in {doc.filename} ({ValidationContext.doc_label(doc)})",
            [
                _build_ref(
                    doc_id=doc.id,
                    field_key=ref.field_key,
                    value=None,
                    normalized=None,
                    present=False,
                    note="missing_field",
                )
            ],
        )

    for record in collection.invalid_records:
        add(
            f"{description}: field {context.field_label(ref)} in {record.document.filename} ({ValidationContext.doc_label(record.document)}) has unparseable value '{record.field.value}'",
            [
                _build_ref(
                    doc_id=record.document.id,
                    field_key=record.field.field_key,
                    value=record.field.value,
                    normalized=None,
                    present=True,
                    page=getattr(record.field, "page", None),
                    bbox=getattr(record.field, "bbox", None),
                    token_refs=getattr(record.field, "token_refs", None),
                    note="invalid_value",
                )
            ],
        )

    return collection.records


def _format_value(value: Any) -> str:
    if value is None:
        return "<missing>"
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _apply_date_rules(context: ValidationContext, validations: List[ValidationMessage]) -> None:
    def _gather_refs(ref: FieldRef) -> Tuple[List[Dict[str, Any]], List[FieldValueRecord], bool]:
        coll = context.collect(ref, _normalize_date)
        refs: List[Dict[str, Any]] = []
        has_valid = False
        if coll.unknown_doc_type:
            refs.append(_build_ref(doc_id=uuid.UUID(int=0), field_key=ref.field_key, present=False, note="unknown_doc_type"))
        if coll.doc_type_missing:
            refs.append(_build_ref(doc_id=uuid.UUID(int=0), field_key=ref.field_key, present=False, note="missing_doc_type"))
        for doc in coll.missing_docs:
            refs.append(_build_ref(doc_id=doc.id, field_key=ref.field_key, present=False, note="missing_field"))
        for rec in coll.records:
            refs.append(_ref_from_field(rec.document, rec.field, normalized=rec.normalized))
            has_valid = True
        for inv in coll.invalid_records:
            refs.append(
                _build_ref(
                    doc_id=inv.document.id,
                    field_key=inv.field.field_key,
                    value=inv.field.value,
                    normalized=None,
                    present=True,
                    page=getattr(inv.field, "page", None),
                    bbox=getattr(inv.field, "bbox", None),
                    token_refs=getattr(inv.field, "token_refs", None),
                    note="invalid_value",
                )
            )
        return refs, coll.records, has_valid

    def _dedupe(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        key_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for r in refs:
            did = str(r.get("doc_id"))
            fkey = r.get("field_key") or ""
            note = r.get("note") or ""
            k = (did, fkey, note)
            prev = key_map.get(k)
            if prev is None:
                key_map[k] = r
            else:
                # prefer present=True over present=False
                if prev.get("present") is False and r.get("present") is True:
                    key_map[k] = r
        return list(key_map.values())

    for rule in DATE_RULES:
        anchor_refs, anchor_recs, anchor_valid = _gather_refs(rule.anchor)
        all_refs: List[Dict[str, Any]] = list(anchor_refs)
        any_other_valid = False
        comparators: List[Tuple[DateComparison, List[FieldValueRecord]]] = []
        for comparison in rule.comparisons:
            other_refs, other_recs, other_valid = _gather_refs(comparison.other)
            all_refs.extend(other_refs)
            any_other_valid = any_other_valid or other_valid
            comparators.append((comparison, other_recs))

        merged_refs = _dedupe(all_refs)

        if not anchor_valid or not any_other_valid:
            validations.append(
                ValidationMessage(
                    rule_id=f"{rule.rule_id}_availability",
                    severity=ValidationSeverity.WARN,
                    message=f"{rule.description}: missing or invalid inputs for date comparison",
                    refs=merged_refs,
                )
            )
            continue

        # Compare all valid pairs and collect mismatches
        op_results: List[Dict[str, Any]] = []
        for comparison, other_recs in comparators:
            op_func = _OPERATOR_FUNC.get(comparison.operator)
            op_text = _OPERATOR_TEXT.get(comparison.operator, comparison.operator)
            if op_func is None:
                continue
            note_suffix = f" ({comparison.note})" if comparison.note else ""
            for a in anchor_recs:
                for b in other_recs:
                    if not op_func(a.normalized, b.normalized):
                        op_results.append(
                            {
                                "message": (
                                    f"{rule.description}: {context.field_label(rule.anchor)} in {a.document.filename}"
                                    f" ({ValidationContext.doc_label(a.document)}) = '{_format_value(a.field.value)}' must be {op_text}"
                                    f" {context.field_label(comparison.other)} in {b.document.filename}"
                                    f" ({ValidationContext.doc_label(b.document)}) = '{_format_value(b.field.value)}'{note_suffix}"
                                )
                            }
                        )
        if op_results:
            # Emit single violation block with merged refs; use first message for readability
            validations.append(
                ValidationMessage(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=op_results[0]["message"],
                    refs=merged_refs,
                )
            )


def _apply_anchored_equality_rules(context: ValidationContext, validations: List[ValidationMessage]) -> None:
    def _norm_kind(kind: str):
        if kind == "date":
            return _normalize_date
        return lambda v: _normalize_value(v, kind)

    def _gather(ref: FieldRef, kind: str) -> Tuple[List[Dict[str, Any]], List[FieldValueRecord], bool]:
        coll = context.collect(ref, _norm_kind(kind))
        refs: List[Dict[str, Any]] = []
        has_valid = False
        if coll.unknown_doc_type:
            refs.append(_build_ref(doc_id=uuid.UUID(int=0), field_key=ref.field_key, present=False, note="unknown_doc_type", doc_type=ref.doc_type))
        if coll.doc_type_missing:
            refs.append(_build_ref(doc_id=uuid.UUID(int=0), field_key=ref.field_key, present=False, note="missing_doc_type", doc_type=ref.doc_type))
        for doc in coll.missing_docs:
            refs.append(_build_ref(doc_id=doc.id, field_key=ref.field_key, present=False, note="missing_field", doc_type=ref.doc_type))
        for rec in coll.records:
            refs.append(_ref_from_field(rec.document, rec.field, normalized=rec.normalized))
            has_valid = True
        for inv in coll.invalid_records:
            refs.append(
                _build_ref(
                    doc_id=inv.document.id,
                    field_key=inv.field.field_key,
                    value=inv.field.value,
                    normalized=None,
                    present=True,
                    page=getattr(inv.field, "page", None),
                    bbox=getattr(inv.field, "bbox", None),
                    token_refs=getattr(inv.field, "token_refs", None),
                    note="invalid_value",
                    doc_type=ref.doc_type,
                )
            )
        return refs, coll.records, has_valid

    def _dedupe(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        key_map: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        for r in refs:
            did = str(r.get("doc_id"))
            fkey = r.get("field_key") or ""
            note = r.get("note") or ""
            dtype = r.get("doc_type") or ""
            k = (did, fkey, note, dtype)
            prev = key_map.get(k)
            if prev is None:
                key_map[k] = r
            else:
                if prev.get("present") is False and r.get("present") is True:
                    key_map[k] = r
        return list(key_map.values())

    for rule in ANCHORED_EQUALITY_RULES:
        all_refs: List[Dict[str, Any]] = []
        anchor_refs, anchor_recs, anchor_valid = _gather(rule.anchor, rule.value_kind)
        all_refs.extend(anchor_refs)
        targets_data: List[Tuple[FieldRef, List[FieldValueRecord], bool]] = []
        any_target_valid = False
        for t in rule.targets:
            rrefs, rrecs, rvalid = _gather(t, rule.value_kind)
            all_refs.extend(rrefs)
            targets_data.append((t, rrecs, rvalid))
            any_target_valid = any_target_valid or rvalid

        merged_refs = _dedupe(all_refs)

        if not anchor_valid or not any_target_valid:
            validations.append(
                ValidationMessage(
                    rule_id=f"{rule.rule_id}_availability",
                    severity=ValidationSeverity.WARN,
                    message=f"{rule.description}: missing or invalid inputs for comparison",
                    refs=merged_refs,
                )
            )
            continue

        # Determine canonical from first anchor record
        canonical = anchor_recs[0].normalized
        if canonical is None:
            validations.append(
                ValidationMessage(
                    rule_id=f"{rule.rule_id}_availability",
                    severity=ValidationSeverity.WARN,
                    message=f"{rule.description}: missing or invalid anchor value",
                    refs=merged_refs,
                )
            )
            continue

        mismatch_found = False
        # Check disagreement between anchors
        for a in anchor_recs[1:]:
            if a.normalized != canonical:
                mismatch_found = True
                break
        # Check targets
        if not mismatch_found:
            for t, recs, _ in targets_data:
                for rec in recs:
                    if rec.normalized != canonical:
                        mismatch_found = True
                        break
                if mismatch_found:
                    break

        if mismatch_found:
            validations.append(
                ValidationMessage(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=f"{rule.description}: values are not consistent with anchor",
                    refs=merged_refs,
                )
            )


def _apply_group_equality_rules(context: ValidationContext, validations: List[ValidationMessage]) -> None:
    def _norm_kind(kind: str):
        if kind == "date":
            return _normalize_date
        return lambda v: _normalize_value(v, kind)

    def _gather(ref: FieldRef, kind: str) -> Tuple[List[Dict[str, Any]], List[FieldValueRecord], bool]:
        coll = context.collect(ref, _norm_kind(kind))
        refs: List[Dict[str, Any]] = []
        has_valid = False
        if coll.unknown_doc_type:
            refs.append(_build_ref(doc_id=uuid.UUID(int=0), field_key=ref.field_key, present=False, note="unknown_doc_type", doc_type=ref.doc_type))
        if coll.doc_type_missing:
            refs.append(_build_ref(doc_id=uuid.UUID(int=0), field_key=ref.field_key, present=False, note="missing_doc_type", doc_type=ref.doc_type))
        for doc in coll.missing_docs:
            refs.append(_build_ref(doc_id=doc.id, field_key=ref.field_key, present=False, note="missing_field", doc_type=ref.doc_type))
        for rec in coll.records:
            refs.append(_ref_from_field(rec.document, rec.field, normalized=rec.normalized))
            has_valid = True
        for inv in coll.invalid_records:
            refs.append(
                _build_ref(
                    doc_id=inv.document.id,
                    field_key=inv.field.field_key,
                    value=inv.field.value,
                    normalized=None,
                    present=True,
                    page=getattr(inv.field, "page", None),
                    bbox=getattr(inv.field, "bbox", None),
                    token_refs=getattr(inv.field, "token_refs", None),
                    note="invalid_value",
                    doc_type=ref.doc_type,
                )
            )
        return refs, coll.records, has_valid

    def _dedupe(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        key_map: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        for r in refs:
            did = str(r.get("doc_id"))
            fkey = r.get("field_key") or ""
            note = r.get("note") or ""
            dtype = r.get("doc_type") or ""
            k = (did, fkey, note, dtype)
            prev = key_map.get(k)
            if prev is None:
                key_map[k] = r
            else:
                if prev.get("present") is False and r.get("present") is True:
                    key_map[k] = r
        return list(key_map.values())

    for rule in GROUP_EQUALITY_RULES:
        all_refs: List[Dict[str, Any]] = []
        groups: Dict[Any, List[FieldValueRecord]] = {}
        has_any_valid = False
        for ref in rule.refs:
            rrefs, rrecs, rvalid = _gather(ref, rule.value_kind)
            all_refs.extend(rrefs)
            if rvalid:
                has_any_valid = True
            for rec in rrecs:
                groups.setdefault(rec.normalized, []).append(rec)

        merged_refs = _dedupe(all_refs)

        if not has_any_valid or len(groups) == 0:
            validations.append(
                ValidationMessage(
                    rule_id=f"{rule.rule_id}_availability",
                    severity=ValidationSeverity.WARN,
                    message=f"{rule.description}: missing or invalid inputs for comparison",
                    refs=merged_refs,
                )
            )
            continue

        if len(groups) > 1:
            validations.append(
                ValidationMessage(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=f"{rule.description}: values are not equal across documents",
                    refs=merged_refs,
                )
            )


# --- Legacy helpers and validations (to be refactored into new rule engine) ---

def _collect_fields(rows: Iterable[FilledField]) -> Dict[uuid.UUID, Dict[str, FilledField]]:
    result: Dict[uuid.UUID, Dict[str, FilledField]] = {}
    for field in rows:
        result.setdefault(field.doc_id, {})[field.field_key] = field
    return result


def _parse_number(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _collect_value(field: Optional[FilledField]) -> Optional[str]:
    if field is None:
        return None
    return field.value


def _build_field_matrix_snapshot(
    documents: List[Document], fields_by_doc: Dict[uuid.UUID, Dict[str, FilledField]]
) -> Dict[str, Any]:
    doc_type_lookup: Dict[str, List[Dict[str, FilledField]]] = {}
    for document in documents:
        doc_type_value = getattr(document.doc_type, "value", str(document.doc_type))
        doc_fields = fields_by_doc.get(document.id, {})
        doc_type_lookup.setdefault(doc_type_value, []).append(doc_fields)

    def _get_field_value(doc_type: str, aliases: List[str]) -> Tuple[str, bool]:
        found = False
        value = ""
        for field_set in doc_type_lookup.get(doc_type, []):
            for alias in aliases:
                field = field_set.get(alias)
                if field and isinstance(field, FilledField):
                    value = field.value or ""
                    found = True
                    if value:
                        return value, True
            if found:
                return value, True
        return "", False

    def _merge_status(current: Optional[str], new: Optional[str]) -> Optional[str]:
        if new is None:
            return current
        priority = {"anchor": 4, "mismatch": 3, "missing": 2, "match": 1, None: 0}
        if priority.get(new, 0) >= priority.get(current, 0):
            return new
        return current

    def _get_mapped_value(doc_type: str, mapping: Dict[str, List[str]]) -> str:
        aliases = mapping.get(doc_type) or []
        if not aliases:
            return ""
        value, _ = _get_field_value(doc_type, aliases)
        return value or ""

    rows: List[Dict[str, Any]] = []

    for label, mapping in (
        ("номер документа", DOCUMENT_NUMBER_FIELDS),
        ("дата документа", DOCUMENT_DATE_FIELDS),
    ):
        row: Dict[str, Any] = {"FieldKey": label}
        statuses: Dict[str, Optional[str]] = {doc: None for doc in FIELD_MATRIX_DOC_TYPES}
        for display_doc in FIELD_MATRIX_DOC_TYPES:
            actual_doc_type = FIELD_MATRIX_DOC_TYPE_MAP.get(display_doc, display_doc)
            value = ""
            if actual_doc_type:
                value = _get_mapped_value(actual_doc_type, mapping)
            row[display_doc] = value
        row["statuses"] = statuses
        rows.append(row)

    for field_key, aliases in FIELD_MATRIX_FIELDS:
        row: Dict[str, Any] = {"FieldKey": field_key}
        statuses: Dict[str, Optional[str]] = {doc: None for doc in FIELD_MATRIX_DOC_TYPES}
        value_cache: Dict[str, Tuple[str, bool]] = {}
        actual_to_display: Dict[str, str] = {}

        for display_doc in FIELD_MATRIX_DOC_TYPES:
            actual_doc_type = FIELD_MATRIX_DOC_TYPE_MAP.get(display_doc, display_doc)
            value = ""
            present = False
            if actual_doc_type:
                value, present = _get_field_value(actual_doc_type, aliases)
                value_cache[actual_doc_type] = (value, present)
                actual_to_display[actual_doc_type] = display_doc
            row[display_doc] = value or ""

        for rule in FIELD_COMPARISON_RULES.get(field_key, []):
            anchor_value, anchor_present = value_cache.get(rule.anchor_doc, ("", False))
            anchor_display = actual_to_display.get(rule.anchor_doc)
            if anchor_display:
                statuses[anchor_display] = _merge_status(statuses[anchor_display], "anchor")
            for target_doc in rule.target_docs:
                target_value, target_present = value_cache.get(target_doc, ("", False))
                target_display = actual_to_display.get(target_doc)
                if not target_display:
                    continue
                if not target_present or target_value == "":
                    status = "missing"
                elif anchor_present and target_value == anchor_value:
                    status = "match"
                elif not anchor_present:
                    status = "missing"
                else:
                    status = "mismatch"
                statuses[target_display] = _merge_status(statuses[target_display], status)

        row["statuses"] = statuses
        rows.append(row)
    return {"documents": FIELD_MATRIX_DOC_TYPES, "rows": rows}


async def fetch_latest_fields(session: AsyncSession, batch_id: uuid.UUID) -> Dict[uuid.UUID, Dict[str, FilledField]]:
    stmt = (
        select(FilledField)
        .join(Document)
        .where(Document.batch_id == batch_id, FilledField.latest.is_(True))
    )
    result = await session.execute(stmt)
    fields = result.scalars().all()
    return _collect_fields(fields)


async def validate_batch(session: AsyncSession, batch_id: uuid.UUID) -> List[ValidationMessage]:
    fields_by_doc = await fetch_latest_fields(session, batch_id)
    doc_stmt = select(Document).where(Document.batch_id == batch_id)
    docs_result = await session.execute(doc_stmt)
    documents = docs_result.scalars().all()

    validations: List[ValidationMessage] = []

    for document in documents:
        schema = get_schema(document.doc_type)
        doc_fields = fields_by_doc.get(document.id, {})
        for key, field_schema in schema.fields.items():
            field = doc_fields.get(key)
            if not field_schema.required:
                continue
            if field is None or (field.value in (None, "")):
                note = "missing_required" if field is None else "empty_required"
                refs = [
                    _build_ref(
                        doc_id=document.id,
                        field_key=key,
                        value=(field.value if field else None),
                        normalized=None,
                        present=bool(field),
                        page=(getattr(field, "page", None) if field else None),
                        bbox=(getattr(field, "bbox", None) if field else None),
                        token_refs=(getattr(field, "token_refs", None) if field else None),
                        note=note,
                    )
                ]
                validations.append(
                    ValidationMessage(
                        rule_id="required_fields",
                        severity=ValidationSeverity.ERROR,
                        message=f"Missing required field {key} in {document.filename}",
                        refs=refs,
                    )
                )

    context = ValidationContext(documents, fields_by_doc)
    _apply_date_rules(context, validations)
    _apply_anchored_equality_rules(context, validations)
    _apply_group_equality_rules(context, validations)

    invoice_numbers = {
        doc_id: _collect_value(fields.get("invoice_no"))
        for doc_id, fields in fields_by_doc.items()
        if "invoice_no" in fields
    }
    unique_invoices = {value for value in invoice_numbers.values() if value}
    if len(unique_invoices) > 1:
        refs = [
            {"doc_id": doc_id, "field_key": "invoice_no", "value": value}
            for doc_id, value in invoice_numbers.items()
        ]
        validations.append(
            ValidationMessage(
                rule_id="invoice_no_alignment",
                severity=ValidationSeverity.ERROR,
                message="Invoice numbers do not match across documents",
                refs=refs,
            )
        )

    # Global weight consistency check disabled; relying on per-product comparisons
    currency_values = {
        doc_id: _collect_value(fields.get("currency"))
        for doc_id, fields in fields_by_doc.items()
        if "currency" in fields
    }
    unique_currency = {value for value in currency_values.values() if value}
    if len(unique_currency) > 1:
        refs = [
            {"doc_id": doc_id, "field_key": "currency", "value": value}
            for doc_id, value in currency_values.items()
            if value
        ]
        validations.append(
            ValidationMessage(
                rule_id="currency_consistency",
                severity=ValidationSeverity.WARN,
                message="Currency values differ across documents",
                refs=refs,
            )
        )

    # Products comparison across documents
    rows_by_doc: Dict[uuid.UUID, List[Dict[str, Optional[str]]]] = {}
    for document in documents:
        doc_fields = fields_by_doc.get(document.id, {})
        rows_by_doc[document.id] = _collect_product_rows_for_doc(doc_fields)

    anchor_doc = _prefer_anchor(documents, rows_by_doc)
    if anchor_doc is not None:
        for document in documents:
            if document.id == anchor_doc.id:
                continue
            _compare_products(anchor_doc, document, rows_by_doc, validations)

    destinations = []
    for doc_id, fields in fields_by_doc.items():
        if "destination" in fields:
            destinations.append((doc_id, "destination", fields["destination"].value))
        if "port_of_discharge" in fields:
            destinations.append((doc_id, "port_of_discharge", fields["port_of_discharge"].value))
    destination_values = {value.strip().upper() for _, _, value in destinations if value}
    if len(destination_values) > 1:
        refs = [
            {"doc_id": doc_id, "field_key": field_key, "value": value}
            for doc_id, field_key, value in destinations
            if value
        ]
        validations.append(
            ValidationMessage(
                rule_id="destination_alignment",
                severity=ValidationSeverity.WARN,
                message="Destination or discharge ports differ between documents",
                refs=refs,
            )
        )

    field_matrix = _build_field_matrix_snapshot(documents, fields_by_doc)
    validations.append(
        ValidationMessage(
            rule_id="document_matrix",
            severity=ValidationSeverity.OK,
            message="Document field matrix snapshot",
            refs=[field_matrix],
        )
    )

    return validations


async def store_validations(session: AsyncSession, batch_id: uuid.UUID, messages: List[ValidationMessage]) -> None:
    await session.execute(delete(Validation).where(Validation.batch_id == batch_id))
    for message in messages:
        serializable_refs = _json_safe(message.refs) if message.refs else None
        session.add(
            Validation(
                batch_id=batch_id,
                rule_id=message.rule_id,
                severity=message.severity,
                message=message.message,
                refs=serializable_refs,
            )
        )
    await session.flush()








