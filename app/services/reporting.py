from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import BatchStatus
from app.core.storage import batch_dir
from app.models import Batch, Document, FilledField, Validation


async def load_batch_with_fields(session: AsyncSession, batch_id: uuid.UUID) -> Batch:
    stmt = (
        select(Batch)
        .where(Batch.id == batch_id)
        .options(selectinload(Batch.documents).selectinload(Document.fields))
    )
    result = await session.execute(stmt)
    batch = result.scalar_one()
    return batch


async def fetch_validations(session: AsyncSession, batch_id: uuid.UUID) -> List[Validation]:
    stmt = select(Validation).where(Validation.batch_id == batch_id)
    result = await session.execute(stmt)
    return result.scalars().all()


def _collapse_spaces(value: str) -> str:
    return " ".join(value.split())


def _normalize_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return _collapse_spaces(trimmed).casefold()


def _field_value(entry: Optional[Any]) -> Optional[str]:
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _product_key(name: Optional[Any], latin: Optional[Any], size: Optional[Any]):
    name = _field_value(name)
    latin = _field_value(latin)
    size = _field_value(size)
    name_k = _normalize_name(name)
    latin_k = _normalize_name(latin)
    size_k = (size.strip() if isinstance(size, str) else None) or None
    if not name_k:
        return None
    if latin_k is None and size_k is None:
        return (name_k,)
    if latin_k is None:
        return (name_k, size_k)
    if size_k is None:
        return (name_k, latin_k)
    return (name_k, latin_k, size_k)


def _collect_products_for_doc(fields_payload: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for key, payload in fields_payload.items():
        if not key.startswith("products."):
            continue
        parts = key.split(".")
        if len(parts) < 3:
            continue
        prod_id = parts[1]
        sub_key = ".".join(parts[2:])
        value = payload.get("value") if isinstance(payload, dict) else None
        entry: Dict[str, Any]
        if isinstance(payload, dict):
            entry = {
                "value": payload.get("value"),
                "confidence": payload.get("confidence"),
            }
        else:
            entry = {"value": payload}
        grouped.setdefault(prod_id, {})[sub_key] = entry
    return grouped


def _round_confidence(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


async def generate_report(session: AsyncSession, batch_id: uuid.UUID) -> Dict[str, Any]:
    batch = await load_batch_with_fields(session, batch_id)
    validations = await fetch_validations(session, batch_id)

    documents_payload: List[Dict[str, Any]] = []
    doc_fields_index: Dict[uuid.UUID, Dict[str, Dict[str, Any]]] = {}
    for document in batch.documents:
        fields_payload = {
            field.field_key: {
                "value": field.value,
                "confidence": _round_confidence(field.confidence),
                "source": field.source,
                "page": field.page,
                "bbox": field.bbox,
            }
            for field in document.fields
            if field.latest
        }
        documents_payload.append(
            {
                "doc_id": str(document.id),
                "filename": document.filename,
                "doc_type": document.doc_type.value,
                "status": document.status.value,
                "fields": fields_payload,
            }
        )
        doc_fields_index[document.id] = fields_payload

    validations_payload = [
        {
            "rule_id": validation.rule_id,
            "severity": validation.severity.value,
            "message": validation.message,
            "refs": validation.refs or [],
        }
        for validation in validations
    ]

    processing_warnings = (batch.meta or {}).get("processing_warnings", [])
    for index, warning in enumerate(processing_warnings, start=1):
        validations_payload.append(
            {
                "rule_id": f"processing_warning_{index}",
                "severity": "warn",
                "message": warning,
                "refs": [],
            }
        )

    # Matched products across documents (for diagnostics/UI)
    product_buckets: Dict[tuple, List[Dict[str, Any]]] = {}
    for document in batch.documents:
        fields_payload = doc_fields_index.get(document.id, {})
        rows = _collect_products_for_doc(fields_payload)
        for prod_id, sub in rows.items():
            key = _product_key(sub.get("name_product"), sub.get("latin_name"), sub.get("size_product"))
            if key is None:
                continue
            product_buckets.setdefault(key, []).append(
                {
                    "doc_id": str(document.id),
                    "doc_type": document.doc_type.value,
                    "product_id": prod_id,
                    "fields": {k: v for k, v in sub.items()},
                }
            )

    product_comparisons: List[Dict[str, Any]] = []
    for key, items in product_buckets.items():
        if len(items) < 2:
            continue

        def first_non_empty(extractor):
            for it in items:
                val = extractor(it)
                if isinstance(val, str) and val.strip():
                    return val
            return None

        product_comparisons.append(
            {
                "product_key": {
                    "name_product": first_non_empty(lambda it: it["fields"].get("name_product")),
                    "latin_name": first_non_empty(lambda it: it["fields"].get("latin_name")),
                    "size_product": first_non_empty(lambda it: it["fields"].get("size_product")),
                },
                "documents": items,
            }
        )

    payload = {
        "batch_id": str(batch.id),
        "status": batch.status.value,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "documents": documents_payload,
        "validations": validations_payload,
        "meta": batch.meta or {},
        "product_comparisons": product_comparisons,
    }

    report_path = batch_dir(str(batch_id)).report
    report_path.mkdir(parents=True, exist_ok=True)
    output_file = report_path / "report.json"
    with output_file.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    if batch.status != BatchStatus.DONE:
        batch.status = BatchStatus.DONE

    return payload
