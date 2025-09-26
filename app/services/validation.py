from __future__ import annotations

import operator
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
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
        description="Proforma date must be the earliest among related documents",
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
        description="Invoice date must not be earlier than shipment and certificate dates",
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
        description="Bill of landing date must be later than proforma, invoice and price lists",
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
        description="Packing list date must be earlier than Bill of landing and not later than invoice",
        anchor=PACKING_LIST_DATE,
        comparisons=[
            DateComparison("<", BOL_DATE),
            DateComparison("<=", INVOICE_DATE),
        ],
    ),
    DateRule(
        rule_id="date_price_list_1_before_proforma",
        description="Price list 1 date must be earlier or equal to proforma date",
        anchor=PRICE_LIST1_DATE,
        comparisons=[DateComparison("<=", PROFORMA_DATE)],
    ),
    DateRule(
        rule_id="date_price_list_2_between_proforma_invoice",
        description="Price list 2 date must be later than proforma and not later than invoice",
        anchor=PRICE_LIST2_DATE,
        comparisons=[
            DateComparison(">", PROFORMA_DATE),
            DateComparison("<=", INVOICE_DATE),
        ],
    ),
    DateRule(
        rule_id="date_quality_certificate_after_bol",
        description="Quality certificate date must be later or equal to Bill of landing date",
        anchor=QUALITY_CERT_DATE,
        comparisons=[DateComparison(">=", BOL_DATE)],
    ),
    DateRule(
        rule_id="date_veterinary_certificate_before_bol",
        description="Veterinary certificate date must be earlier than Bill of landing date",
        anchor=VET_CERT_DATE,
        comparisons=[DateComparison("<", BOL_DATE)],
    ),
    DateRule(
        rule_id="date_export_declaration_after_bol",
        description="Export declaration date must be later or equal to Bill of landing date",
        anchor=EXPORT_DECL_DATE,
        comparisons=[DateComparison(">=", BOL_DATE)],
    ),
    DateRule(
        rule_id="date_specification_not_after_invoice",
        description="Specification date must not be later than invoice date",
        anchor=SPECIFICATION_DATE,
        comparisons=[DateComparison("<=", INVOICE_DATE)],
    ),
    DateRule(
        rule_id="date_certificate_origin_after_invoice",
        description="Certificate of origin date must be later or equal to invoice date",
        anchor=CERT_ORIGIN_DATE,
        comparisons=[DateComparison(">=", INVOICE_DATE)],
    ),
]


ANCHORED_EQUALITY_RULES: List[AnchoredEqualityRule] = [
    AnchoredEqualityRule(
        rule_id="contract_no_alignment",
        description="Contract number must match across Proforma, Invoice and Specification",
        anchor=_ref("PROFORMA", "contract_no", "Contract number"),
        targets=[
            _ref("INVOICE", "contract_no"),
            _ref("SPECIFICATION", "contract_no"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="additional_agreements_alignment",
        description="Additional agreements must match across Proforma, Invoice and Specification",
        anchor=_ref("PROFORMA", "additional_agreements", "Additional agreements"),
        targets=[
            _ref("INVOICE", "additional_agreements"),
            _ref("SPECIFICATION", "additional_agreements"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="country_of_origin_consistency",
        description="Country of origin must match the veterinary certificate across documents",
        anchor=_ref("VETERINARY_CERTIFICATE", "country_of_origin", "Country of origin"),
        targets=_refs(ALL_DOC_TYPES, "country_of_origin", exclude=["VETERINARY_CERTIFICATE"]),
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="producer_consistency",
        description="Producer must match the veterinary certificate across documents",
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
        description="Incoterms must match the invoice",
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
        description="Terms of payment must match the invoice",
        anchor=_ref("INVOICE", "terms_of_payment", "Terms of payment"),
        targets=[
            _ref("PROFORMA", "terms_of_payment"),
            _ref("SPECIFICATION", "terms_of_payment"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="bank_details_consistency",
        description="Bank details must match between invoice and proforma",
        anchor=_ref("INVOICE", "bank_details", "Bank details"),
        targets=[_ref("PROFORMA", "bank_details")],
    ),
    AnchoredEqualityRule(
        rule_id="exporter_consistency",
        description="Exporter must match the veterinary certificate",
        anchor=_ref("VETERINARY_CERTIFICATE", "exporter", "Exporter"),
        targets=[
            _ref("BILL_OF_LANDING", "exporter"),
            _ref("CERTIFICATE_OF_ORIGIN", "exporter"),
        ],
        value_kind="string-casefold",
    ),
    AnchoredEqualityRule(
        rule_id="total_price_consistency",
        description="Total price must match the invoice",
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
        description="Packages count must match the packing list",
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
        rule_id="net_weight_consistency",
        description="Net weight must match the veterinary certificate",
        anchor=_ref("VETERINARY_CERTIFICATE", "net_weight", "Net weight"),
        targets=[
            _ref("PACKING_LIST", "net_weight"),
            _ref("PROFORMA", "net_weight"),
            _ref("BILL_OF_LANDING", "net_weight"),
            _ref("CERTIFICATE_OF_ORIGIN", "net_weight"),
            _ref("EXPORT_DECLARATION", "net_weight"),
            _ref("QUALITY_CERTIFICATE", "net_weight"),
        ],
        value_kind="number",
    ),
    AnchoredEqualityRule(
        rule_id="gross_weight_consistency",
        description="Gross weight must match the packing list",
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
        description="Invoice number must match across key documents",
        anchor=_ref("INVOICE", "invoice_no", "Invoice number"),
        targets=[
            _ref("PACKING_LIST", "invoice_no"),
            _ref("EXPORT_DECLARATION", "invoice_no"),
            _ref("CERTIFICATE_OF_ORIGIN", "invoice_no"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="veterinary_seal_consistency",
        description="Veterinary seal must match the veterinary certificate",
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
        description="Linear seal must match the Bill of landing",
        anchor=_ref("BILL_OF_LANDING", "linear_seal", "Linear seal"),
        targets=[
            _ref("QUALITY_CERTIFICATE", "linear_seal"),
            _ref("CERTIFICATE_OF_ORIGIN", "linear_seal"),
            _ref("PACKING_LIST", "linear_seal"),
        ],
    ),
    AnchoredEqualityRule(
        rule_id="name_product_consistency",
        description="Product name must match the invoice across documents",
        anchor=_ref("INVOICE", "name_product", "Product name"),
        targets=_refs(ALL_DOC_TYPES, "name_product", exclude=["INVOICE"]),
    ),
    AnchoredEqualityRule(
        rule_id="latin_name_consistency",
        description="Latin name must match the veterinary certificate across documents",
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
        description="Buyer must be identical across Proforma, Invoice, Export declaration, Specification, Veterinary certificate and Certificate of origin",
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
        description="Seller must be identical across Proforma, Invoice, Export declaration, Specification and price lists",
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
        description="Container number must match across all shipping documents",
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
        description="Vessel (or vehicle) must match across key documents",
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
        description="Importer must match between Bill of landing and certificate of origin",
        refs=[
            _ref("BILL_OF_LANDING", "importer"),
            _ref("CERTIFICATE_OF_ORIGIN", "importer"),
        ],
    ),
    GroupEqualityRule(
        rule_id="unit_box_alignment",
        description="Unit box (packaging type) must match across documents",
        refs=_refs(ALL_DOC_TYPES, "unit_box"),
    ),
    GroupEqualityRule(
        rule_id="size_product_alignment",
        description="Product size must match across documents",
        refs=_refs(ALL_DOC_TYPES, "size_product"),
    ),
]


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

    weight_fields = []
    for doc_id, fields in fields_by_doc.items():
        for key in ("net_weight", "gross_weight"):
            number = _parse_number(_collect_value(fields.get(key)))
            if number is not None:
                weight_fields.append((doc_id, key, number))
    if weight_fields:
        values = [item[2] for item in weight_fields]
        if max(values) - min(values) > 1.0:
            refs = [
                {"doc_id": doc_id, "field_key": key, "value": value}
                for doc_id, key, value in weight_fields
            ]
            validations.append(
                ValidationMessage(
                    rule_id="weight_consistency",
                    severity=ValidationSeverity.WARN,
                    message="Weight values differ more than 1.0 across documents",
                    refs=refs,
                )
            )

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
        session.add(
            Validation(
                batch_id=batch_id,
                rule_id=message.rule_id,
                severity=message.severity,
                message=message.message,
                refs=message.refs,
            )
        )
    await session.flush()






