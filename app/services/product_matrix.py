from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.document_profiles import get_field_matrix_doc_types
from app.core.enums import DocumentType
from app.core.schema import get_schema

PRODUCT_SUM_FIELDS: List[Tuple[str, str]] = [
    ("packages", "Packages"),
    ("net_weight", "Net Weight"),
    ("net_weight_with_glaze", "Net Weight with Glaze"),
    ("net_weight_with_ice", "Net Weight with Ice"),
    ("net_weight_with_glaze_and_pack", "Net Weight with Glaze and Pack"),
    ("gross_weight", "Gross Weight"),
]

_PRODUCT_PREFIX = "products."
_NUMERIC_TOKEN_RE = re.compile(r"[-+]?\d(?:[\d.,\s]*\d)?")


@dataclass(frozen=True)
class AggregateValue:
    value: Optional[str]
    normalized_value: Optional[str]
    decimal_value: Optional[Decimal]
    reliable: bool
    has_rows: bool


def product_matrix_columns() -> List[Dict[str, str]]:
    return [{"key": key, "label": label} for key, label in PRODUCT_SUM_FIELDS]


def build_product_matrix(
    documents_payload: List[Dict[str, Any]],
    *,
    document_profile: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    eligible_docs = _ordered_product_documents(documents_payload, document_profile=document_profile)
    if not eligible_docs:
        return product_matrix_columns(), []

    aggregate_cache: Dict[str, Dict[str, AggregateValue]] = {}
    anchor_doc_id: Optional[str] = None
    for doc in eligible_docs:
        doc_id = _doc_id(doc)
        if doc_id is None:
            continue
        aggregate_cache[doc_id] = {
            field_key: _aggregate_product_field(_collect_product_rows(doc), field_key)
            for field_key, _ in PRODUCT_SUM_FIELDS
        }
        if anchor_doc_id is None and doc.get("doc_type") == DocumentType.PACKING_LIST.value:
            anchor_doc_id = doc_id

    rows: List[Dict[str, Any]] = []
    for doc in eligible_docs:
        doc_id = _doc_id(doc)
        if doc_id is None:
            continue
        supported_fields = _supported_product_fields(doc.get("doc_type"))
        anchor_values = aggregate_cache.get(anchor_doc_id, {}) if anchor_doc_id else {}
        doc_values = aggregate_cache.get(doc_id, {})
        cells: Dict[str, Dict[str, Any]] = {}
        for field_key, _ in PRODUCT_SUM_FIELDS:
            supported = field_key in supported_fields
            if not supported:
                cells[field_key] = {
                    "value": None,
                    "normalized_value": None,
                    "status": None,
                    "supported": False,
                }
                continue

            aggregate = doc_values.get(field_key) or AggregateValue(
                value=None,
                normalized_value=None,
                decimal_value=None,
                reliable=False,
                has_rows=False,
            )
            if doc_id == anchor_doc_id:
                status = "anchor"
            else:
                anchor_aggregate = anchor_values.get(field_key)
                if (
                    anchor_doc_id is None
                    or anchor_aggregate is None
                    or not anchor_aggregate.reliable
                    or anchor_aggregate.decimal_value is None
                ):
                    status = "missing"
                elif not aggregate.reliable or aggregate.decimal_value is None:
                    status = "missing"
                elif aggregate.decimal_value == anchor_aggregate.decimal_value:
                    status = "match"
                else:
                    status = "mismatch"
            cells[field_key] = {
                "value": aggregate.value,
                "normalized_value": aggregate.normalized_value,
                "status": status,
                "supported": True,
            }

        rows.append(
            {
                "doc_id": doc_id,
                "doc_type": doc.get("doc_type"),
                "filename": doc.get("filename"),
                "cells": cells,
            }
        )

    return product_matrix_columns(), rows


def _ordered_product_documents(
    documents_payload: Iterable[Dict[str, Any]],
    *,
    document_profile: str,
) -> List[Dict[str, Any]]:
    profile_order = {doc_type: index for index, doc_type in enumerate(get_field_matrix_doc_types(document_profile))}
    default_order = len(profile_order)
    eligible: List[Tuple[int, int, Dict[str, Any]]] = []
    for batch_index, document in enumerate(documents_payload):
        if not _supported_product_fields(document.get("doc_type")):
            continue
        order_index = profile_order.get(str(document.get("doc_type")), default_order)
        eligible.append((order_index, batch_index, document))
    eligible.sort(key=lambda item: (item[0], item[1]))
    return [document for _, _, document in eligible]


def _collect_product_rows(document_payload: Dict[str, Any]) -> List[Dict[str, Optional[str]]]:
    fields_payload = document_payload.get("fields") or {}
    if not isinstance(fields_payload, dict):
        return []

    grouped: Dict[str, Dict[str, Optional[str]]] = {}
    for key, payload in fields_payload.items():
        if not isinstance(key, str) or not key.startswith(_PRODUCT_PREFIX):
            continue
        parts = key.split(".")
        if len(parts) < 3:
            continue
        product_id = parts[1]
        if product_id == "product_template":
            continue
        sub_key = ".".join(parts[2:])
        value = _field_value(payload)
        grouped.setdefault(product_id, {"__id": product_id})[sub_key] = value

    def _product_order_key(product_id: str) -> Tuple[int, str]:
        match = re.search(r"\d+", product_id)
        if match:
            return int(match.group(0)), product_id
        return 1_000_000_000, product_id

    return [grouped[product_id] for product_id in sorted(grouped.keys(), key=_product_order_key)]


def _field_value(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        value = payload.get("value")
        return value if isinstance(value, str) else (None if value is None else str(value))
    if payload is None:
        return None
    return payload if isinstance(payload, str) else str(payload)


def _supported_product_fields(raw_doc_type: Any) -> set[str]:
    doc_type = _resolve_doc_type(raw_doc_type)
    if doc_type is None:
        return set()
    schema = get_schema(doc_type)
    products_schema = schema.fields.get("products")
    if not products_schema or not products_schema.children:
        return set()
    template = products_schema.children.get("product_template")
    if not template or not template.children:
        return set()
    return set(template.children.keys())


def _resolve_doc_type(raw_doc_type: Any) -> Optional[DocumentType]:
    if isinstance(raw_doc_type, DocumentType):
        return raw_doc_type
    if not isinstance(raw_doc_type, str):
        return None
    if raw_doc_type in DocumentType.__members__:
        return DocumentType.__members__[raw_doc_type]
    for doc_type in DocumentType:
        if doc_type.value == raw_doc_type:
            return doc_type
    return None


def _aggregate_product_field(rows: List[Dict[str, Optional[str]]], field_key: str) -> AggregateValue:
    if not rows:
        return AggregateValue(value=None, normalized_value=None, decimal_value=None, reliable=False, has_rows=False)

    total = Decimal("0")
    for row in rows:
        raw_value = row.get(field_key)
        if raw_value is None or not raw_value.strip():
            return AggregateValue(value=None, normalized_value=None, decimal_value=None, reliable=False, has_rows=True)
        parsed = _parse_semicolon_sum(raw_value)
        if parsed is None:
            return AggregateValue(value=None, normalized_value=None, decimal_value=None, reliable=False, has_rows=True)
        total += parsed

    normalized = _decimal_to_string(total)
    return AggregateValue(
        value=normalized,
        normalized_value=normalized,
        decimal_value=total,
        reliable=True,
        has_rows=True,
    )


def _parse_semicolon_sum(raw_value: str) -> Optional[Decimal]:
    parts = [part.strip() for part in raw_value.split(";") if part.strip()]
    if not parts:
        return None
    total = Decimal("0")
    for part in parts:
        parsed = _parse_decimal_segment(part)
        if parsed is None:
            return None
        total += parsed
    return total


def _parse_decimal_segment(segment: str) -> Optional[Decimal]:
    matches = _NUMERIC_TOKEN_RE.findall(segment)
    if len(matches) != 1:
        return None

    token = matches[0].replace(" ", "")
    if not token:
        return None

    sign = ""
    if token[0] in "+-":
        sign = token[0]
        token = token[1:]
    if not token or not any(char.isdigit() for char in token):
        return None

    decimal_sep = _decimal_separator_for_token(token)
    if decimal_sep is None:
        candidate = f"{sign}{token.replace('.', '').replace(',', '')}"
    else:
        integer_part, fractional_part = token.rsplit(decimal_sep, 1)
        if not fractional_part:
            return None
        integer_part = integer_part.replace(".", "").replace(",", "")
        fractional_part = fractional_part.replace(".", "").replace(",", "")
        if not integer_part:
            integer_part = "0"
        candidate = f"{sign}{integer_part}.{fractional_part}"

    try:
        return Decimal(candidate)
    except InvalidOperation:
        return None


def _decimal_separator_for_token(token: str) -> Optional[str]:
    dot_index = token.rfind(".")
    comma_index = token.rfind(",")
    if dot_index == -1 and comma_index == -1:
        return None
    if dot_index != -1 and comma_index != -1:
        if dot_index > comma_index:
            return "."
        return ","

    separator = "." if dot_index != -1 else ","
    groups = token.split(separator)
    if len(groups) > 1 and all(group.isdigit() and len(group) == 3 for group in groups[1:]):
        return None
    if dot_index > comma_index:
        return "."
    return ","


def _decimal_to_string(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _doc_id(document_payload: Dict[str, Any]) -> Optional[str]:
    raw_doc_id = document_payload.get("doc_id")
    if raw_doc_id is None:
        return None
    return str(raw_doc_id)
