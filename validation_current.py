from __future__ import annotations


    # Disabled anchored equality for gross weight
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
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

    # Missing in target
    for key, cnt in anchor_ms.items():
        delta = cnt - target_ms.get(key, 0)
        if delta > 0:
            validations.append(
                ValidationMessage(
                    rule_id=f"products_missing_in_{target_doc.doc_type.name}",
                    severity=ValidationSeverity.ERROR,
                    message=f"{delta} product(s) missing in {target_doc.doc_type.name} compared to {anchor_doc.doc_type.name}",
                    refs=[{"doc_id": target_doc.id, "field_key": "products"}],
                )
            )

    # Extra in target
    for key, cnt in target_ms.items():
        delta = cnt - anchor_ms.get(key, 0)
        if delta > 0:
            validations.append(
                ValidationMessage(
                    rule_id=f"products_extra_in_{target_doc.doc_type.name}",
                    severity=ValidationSeverity.WARN,
                    message=f"{delta} extra product(s) in {target_doc.doc_type.name} versus {anchor_doc.doc_type.name}",
                    refs=[{"doc_id": target_doc.id, "field_key": "products"}],
            )
        )

    # Count mismatch where both have entries
    for key in set(anchor_ms.keys()).intersection(set(target_ms.keys())):
        a, b = anchor_ms[key], target_ms[key]
        if a != b:
            validations.append(
                ValidationMessage(
                    rule_id=f"products_count_mismatch_{target_doc.doc_type.name}",
                    severity=ValidationSeverity.WARN,
                    message=f"Product count for a matched key differs: {a} vs {b}",
                    refs=[{"doc_id": target_doc.id, "field_key": "products"}],
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

    def _value_for_compare(field_key: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if field_key in ("name_product", "latin_name"):
            return _normalize_name_for_key(value)
        return value.strip()

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
                                {"doc_id": anchor_doc.id, "field_key": f"products.{prod_id_a}.{fkey}"},
                                {"doc_id": target_doc.id, "field_key": f"products.{prod_id_b}.{fkey}"},
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
]


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
        comparisons=[DateComparison(">=", BOL_DATE)],
    ),
    DateRule(
        rule_id="date_veterinary_certificate_before_bol",
        description="Дата ветеринарного сертификата должна быть раньше чем дата коноссамента",
        anchor=VET_CERT_DATE,
        comparisons=[DateComparison("<", BOL_DATE)],
    ),
    DateRule(
        rule_id="date_export_declaration_after_bol",
        description="Дата экспортной декларации должна быть позже или равна даты коноссамента",
        anchor=EXPORT_DECL_DATE,
        comparisons=[DateComparison(">=", BOL_DATE)],
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
]


ANCHORED_EQUALITY_RULES: List[AnchoredEqualityRule] = [
    AnchoredEqualityRule(
        rule_id="contract_no_alignment",
        description="Номер контракта должен быть одинаковым среди проформы, инвойса и спецификации",
        anchor=_ref("PROFORMA", "contract_no", "Contract number"),
        targets=[
            _ref("INVOICE", "contract_no"),
            _ref("SPECIFICATION", "contract_no"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="additional_agreements_alignment",
        description="Дополнительное соглашение дожно быть одинаковым среди профомы, инвойса и спецификации",
        anchor=_ref("PROFORMA", "additional_agreements", "Additional agreements"),
        targets=[
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
            _ref("PROFORMA", "incoterms"),
            _ref("PRICE_LIST_1", "incoterms"),
            _ref("PRICE_LIST_2", "incoterms"),
            _ref("EXPORT_DECLARATION", "incoterms"),
            _ref("SPECIFICATION", "incoterms"),
        ],
        value_kind="string-upper",
    ),
    AnchoredEqualityRule(
        rule_id="terms_of_payment_consistency",
        description="Условия оплаты из инвойса должны совпадать с другими документами",
        anchor=_ref("INVOICE", "terms_of_payment", "Terms of payment"),
        targets=[
            _ref("PROFORMA", "terms_of_payment"),
            _ref("SPECIFICATION", "terms_of_payment"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="bank_details_consistency",
        description="Банковские данные должны совпадать в инвойсе и проформе",
        anchor=_ref("INVOICE", "bank_details", "Bank details"),
        targets=[_ref("PROFORMA", "bank_details")],
    ),
    AnchoredEqualityRule(
        rule_id="exporter_consistency",
        description="Экспортер в ветеринарном сертификате должен совпадать с другими",
        anchor=_ref("VETERINARY_CERTIFICATE", "exporter", "Exporter"),
        targets=[
            _ref("BILL_OF_LANDING", "exporter"),
            _ref("CERTIFICATE_OF_ORIGIN", "exporter"),
        ],
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="total_price_consistency",
        description="Итоговая цена в инвойсе должна совпадать с другими документами",
        anchor=_ref("INVOICE", "total_price", "Total price"),
        targets=[
            _ref("PROFORMA", "total_price"),
            _ref("SPECIFICATION", "total_price"),
            _ref("EXPORT_DECLARATION", "total_price"),
            _ref("PRICE_LIST_1", "total_price"),
            _ref("PRICE_LIST_2", "total_price"),
        ],
        value_kind="string",
    ),
    AnchoredEqualityRule(
        rule_id="packages_consistency",
        description="Количество упаковок в пакинг листе должно совпадать с другими документами",
        anchor=_ref("PACKING_LIST", "packages", "Packages"),
        targets=[
            _ref("INVOICE", "packages"),
            _ref("BILL_OF_LANDING", "packages"),
            _ref("CERTIFICATE_OF_ORIGIN", "packages"),
            _ref("VETERINARY_CERTIFICATE", "packages"),
            _ref("EXPORT_DECLARATION", "packages"),
            _ref("SPECIFICATION", "packages"),
            _ref("QUALITY_CERTIFICATE", "packages"),
        ],
        value_kind="number",
    ),
    AnchoredEqualityRule(
    # Disabled anchored equality for net/gross weights
        anchor=_ref("PACKING_LIST", "gross_weight", "Gross weight"),
        targets=[
            _ref("BILL_OF_LANDING", "gross_weight"),
            _ref("EXPORT_DECLARATION", "gross_weight"),
            _ref("CERTIFICATE_OF_ORIGIN", "gross_weight"),
        ],
        value_kind="number",
    ),
    AnchoredEqualityRule(
        rule_id="invoice_number_consistency",
        description="Номер инвойса должен совпадать с другими документами",
        anchor=_ref("INVOICE", "invoice_no", "Invoice number"),
        targets=[
            _ref("PACKING_LIST", "invoice_no"),
            _ref("EXPORT_DECLARATION", "invoice_no"),
            _ref("CERTIFICATE_OF_ORIGIN", "invoice_no"),
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
        ],
    ),
    AnchoredEqualityRule(
        rule_id="name_product_consistency",
        description="Наименование продукта должно совпадать с другими документами",
        anchor=_ref("INVOICE", "name_product", "Product name"),
        targets=_refs(ALL_DOC_TYPES, "name_product", exclude=["INVOICE"]),
    ),
    AnchoredEqualityRule(
        rule_id="latin_name_consistency",
        description="Латинское наименование в ветеринарном сертификате должно совпадать с другими документами",
        anchor=_ref("VETERINARY_CERTIFICATE", "latin_name", "Latin name"),
        targets=_refs(ALL_DOC_TYPES, "latin_name", exclude=["VETERINARY_CERTIFICATE"]),
    ),
    AnchoredEqualityRule(
        rule_id="commodity_code_consistency",
        description="Commodity code must match the invoice across documents",
        anchor=_ref("INVOICE", "commodity_code", "Commodity code"),
        targets=_refs(ALL_DOC_TYPES, "commodity_code", exclude=["INVOICE"]),
    ),
]


GROUP_EQUALITY_RULES: List[GroupEqualityRule] = [
    GroupEqualityRule(
        rule_id="buyer_alignment",
        description="Покупатель должен быть одинаковый среди проформы, инвойса, экспортной декларации, спецификации, ветеринарного сертификата и серфтификата происхождения",
        refs=[
            _ref("PROFORMA", "buyer"),
            _ref("INVOICE", "buyer"),
            _ref("EXPORT_DECLARATION", "buyer"),
            _ref("SPECIFICATION", "buyer"),
            _ref("VETERINARY_CERTIFICATE", "buyer"),
            _ref("CERTIFICATE_OF_ORIGIN", "buyer"),
        ],
    ),
    GroupEqualityRule(
        rule_id="seller_alignment",
        description="Seller must be identical across Proforma, Invoice, Export declaration, Specification and price lists" \
        "Продавец должен быть одинаковый среди проформы, инвойса, экспортной декларации, спецификации и прайс листов",
        refs=[
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
        ],
    ),
    GroupEqualityRule(
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
        add(
            f"{description}: document type '{ref.doc_type}' is not defined in the system",
            [],
        )
        return []

    if collection.doc_type_missing:
        add(
            f"{description}: documents of type {_doc_label(ref.doc_type)} are missing in the batch",
            [],
        )

    for doc in collection.missing_docs:
        add(
            f"{description}: field {context.field_label(ref)} missing in {doc.filename} ({ValidationContext.doc_label(doc)})",
            [{"doc_id": doc.id, "field_key": ref.field_key}],
        )

    for record in collection.invalid_records:
        add(
            f"{description}: field {context.field_label(ref)} in {record.document.filename} ({ValidationContext.doc_label(record.document)}) has unparseable value '{record.field.value}'",
            [{"doc_id": record.document.id, "field_key": record.field.field_key, "value": record.field.value}],
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
    for rule in DATE_RULES:
        anchor_records = _collect_records_for_rule(
            context,
            rule.anchor,
            "date",
            rule.rule_id,
            rule.description,
            validations,
        )
        if not anchor_records:
            continue

        for comparison in rule.comparisons:
            other_records = _collect_records_for_rule(
                context,
                comparison.other,
                "date",
                rule.rule_id,
                rule.description,
                validations,
            )
            if not other_records:
                continue

            op_func = _OPERATOR_FUNC.get(comparison.operator)
            op_text = _OPERATOR_TEXT.get(comparison.operator, comparison.operator)
            if op_func is None:
                continue

            note_suffix = f" ({comparison.note})" if comparison.note else ""

            for anchor in anchor_records:
                for other in other_records:
                    if not op_func(anchor.normalized, other.normalized):
                        message = (
                            f"{rule.description}: {context.field_label(rule.anchor)} in {anchor.document.filename}"
                            f" ({ValidationContext.doc_label(anchor.document)}) = '{_format_value(anchor.field.value)}' must be {op_text}"
                            f" {context.field_label(comparison.other)} in {other.document.filename}"
                            f" ({ValidationContext.doc_label(other.document)}) = '{_format_value(other.field.value)}'{note_suffix}"
                        )
                        refs = [
                            {
                                "doc_id": anchor.document.id,
                                "field_key": anchor.field.field_key,
                                "value": anchor.field.value,
                            },
                            {
                                "doc_id": other.document.id,
                                "field_key": other.field.field_key,
                                "value": other.field.value,
                            },
                        ]
                        validations.append(
                            ValidationMessage(
                                rule_id=rule.rule_id,
                                severity=rule.severity,
                                message=message,
                                refs=refs,
                            )
                        )


def _apply_anchored_equality_rules(context: ValidationContext, validations: List[ValidationMessage]) -> None:
    for rule in ANCHORED_EQUALITY_RULES:
        anchor_records = _collect_records_for_rule(
            context,
            rule.anchor,
            rule.value_kind,
            rule.rule_id,
            rule.description,
            validations,
        )
        if not anchor_records:
            continue

        canonical = anchor_records[0].normalized
        if canonical is None:
            continue

        for anchor in anchor_records[1:]:
            if anchor.normalized != canonical:
                message = (
                    f"{rule.description}: anchor documents disagree on value of {context.field_label(rule.anchor)}"
                    f" ({anchor_records[0].document.filename} = '{_format_value(anchor_records[0].field.value)}',"
                    f" {anchor.document.filename} = '{_format_value(anchor.field.value)}')"
                )
                refs = [
                    {
                        "doc_id": anchor_records[0].document.id,
                        "field_key": anchor_records[0].field.field_key,
                        "value": anchor_records[0].field.value,
                    },
                    {
                        "doc_id": anchor.document.id,
                        "field_key": anchor.field.field_key,
                        "value": anchor.field.value,
                    },
                ]
                validations.append(
                    ValidationMessage(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=message,
                        refs=refs,
                    )
                )

        for target in rule.targets:
            target_records = _collect_records_for_rule(
                context,
                target,
                rule.value_kind,
                rule.rule_id,
                rule.description,
                validations,
            )
            for record in target_records:
                if record.normalized != canonical:
                    message = (
                        f"{rule.description}: {context.field_label(target)} in {record.document.filename}"
                        f" ({ValidationContext.doc_label(record.document)}) = '{_format_value(record.field.value)}'"
                        f" does not match anchor value '{_format_value(anchor_records[0].field.value)}'"
                    )
                    refs = [
                        {
                            "doc_id": anchor_records[0].document.id,
                            "field_key": anchor_records[0].field.field_key,
                            "value": anchor_records[0].field.value,
                        },
                        {
                            "doc_id": record.document.id,
                            "field_key": record.field.field_key,
                            "value": record.field.value,
                        },
                    ]
                    validations.append(
                        ValidationMessage(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=message,
                            refs=refs,
                        )
                    )


def _apply_group_equality_rules(context: ValidationContext, validations: List[ValidationMessage]) -> None:
    for rule in GROUP_EQUALITY_RULES:
        all_records: List[Tuple[FieldRef, FieldValueRecord]] = []
        for ref in rule.refs:
            records = _collect_records_for_rule(
                context,
                ref,
                rule.value_kind,
                rule.rule_id,
                rule.description,
                validations,
            )
            all_records.extend((ref, record) for record in records)

        if len(all_records) <= 1:
            continue

        values_map: Dict[Any, List[Tuple[FieldRef, FieldValueRecord]]] = {}
        for ref, record in all_records:
            values_map.setdefault(record.normalized, []).append((ref, record))

        if len(values_map) <= 1:
            continue

        parts = []
        refs: List[Dict[str, object]] = []
        for normalized_value, records in values_map.items():
            doc_parts = []
            for ref, record in records:
                doc_parts.append(f"{record.document.filename} ({ValidationContext.doc_label(record.document)})")
                refs.append(
                    {
                        "doc_id": record.document.id,
                        "field_key": record.field.field_key,
                        "value": record.field.value,
                    }
                )
            parts.append(
                f"'{_format_value(records[0][1].field.value)}' in {', '.join(doc_parts)}"
            )

        message = f"{rule.description}: values differ across documents: " + "; ".join(parts)
        validations.append(
            ValidationMessage(
                rule_id=rule.rule_id,
                severity=rule.severity,
                message=message,
                refs=refs,
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
            if field_schema.required and (field is None or not field.value):
                validations.append(
                    ValidationMessage(
                        rule_id="required_fields",
                        severity=ValidationSeverity.ERROR,
                        message=f"Missing required field {key} in {document.filename}",
                        refs=[{"doc_id": document.id, "field_key": key}],
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









