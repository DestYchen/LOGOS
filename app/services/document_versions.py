from __future__ import annotations

import difflib
import uuid
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.core.enums import DocumentType
from app.models import Document, FilledField


VERSIONED_TYPES = {
    DocumentType.INVOICE,
    DocumentType.PROFORMA,
    DocumentType.SPECIFICATION,
    DocumentType.PACKING_LIST,
}

STRONG_ID_FIELDS = {
    DocumentType.INVOICE: ("invoice_no",),
    DocumentType.PROFORMA: ("invoice_no", "proforma_no"),
    DocumentType.SPECIFICATION: ("contract_no", "specification_no"),
    DocumentType.PACKING_LIST: ("invoice_no", "packing_list_no", "container_no"),
}

TEXT_SIMILARITY_THRESHOLD = 0.90


def mark_alternative_versions(batch_meta: Mapping[str, Any] | None, documents: Sequence[Document]) -> Dict[str, Any]:
    meta = dict(batch_meta) if isinstance(batch_meta, Mapping) else {}
    entries: Dict[str, Dict[str, Any]] = {}

    eligible = [
        document
        for document in documents
        if document.doc_type in VERSIONED_TYPES and getattr(document, "fields", None)
    ]
    grouped: Dict[DocumentType, List[Document]] = defaultdict(list)
    for document in eligible:
        grouped[document.doc_type].append(document)

    for doc_type, docs in grouped.items():
        primaries: List[Document] = []
        for document in docs:
            match = _find_primary(document, primaries)
            if match is None:
                primaries.append(document)
                entries[str(document.id)] = {
                    "version_role": "primary",
                    "duplicate_group_id": f"{doc_type.value.lower()}_{len(primaries)}",
                }
                continue

            primary, reason, score = match
            primary_entry = entries.setdefault(
                str(primary.id),
                {
                    "version_role": "primary",
                    "duplicate_group_id": f"{doc_type.value.lower()}_{primaries.index(primary) + 1}",
                },
            )
            entries[str(document.id)] = {
                "version_role": "alternative",
                "primary_doc_id": str(primary.id),
                "duplicate_group_id": primary_entry["duplicate_group_id"],
                "reason": reason,
                "similarity": score,
            }

    if entries:
        meta["document_versions"] = entries
    else:
        meta.pop("document_versions", None)
    return meta


def alternative_document_ids(batch_meta: Mapping[str, Any] | None) -> Set[uuid.UUID]:
    versions = _versions(batch_meta)
    result: Set[uuid.UUID] = set()
    for doc_id, entry in versions.items():
        if not isinstance(entry, Mapping) or entry.get("version_role") != "alternative":
            continue
        try:
            result.add(uuid.UUID(str(doc_id)))
        except ValueError:
            continue
    return result


def document_version_entry(batch_meta: Mapping[str, Any] | None, doc_id: uuid.UUID | str) -> Optional[Dict[str, Any]]:
    entry = _versions(batch_meta).get(str(doc_id))
    return dict(entry) if isinstance(entry, Mapping) else None


def is_alternative_document(batch_meta: Mapping[str, Any] | None, doc_id: uuid.UUID | str) -> bool:
    entry = document_version_entry(batch_meta, doc_id)
    return bool(entry and entry.get("version_role") == "alternative")


def _versions(batch_meta: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(batch_meta, Mapping):
        return {}
    versions = batch_meta.get("document_versions")
    return versions if isinstance(versions, Mapping) else {}


def _find_primary(document: Document, primaries: List[Document]) -> Optional[Tuple[Document, str, float]]:
    for primary in primaries:
        strong_match = _strong_id_match(document, primary)
        if strong_match is not None:
            return primary, strong_match, 1.0

        similarity = _text_similarity(_document_signature(document), _document_signature(primary))
        if similarity >= TEXT_SIMILARITY_THRESHOLD:
            return primary, "text_similarity", round(similarity, 4)
    return None


def _strong_id_match(left: Document, right: Document) -> Optional[str]:
    for field_key in STRONG_ID_FIELDS.get(left.doc_type, ()):
        left_value = _field_value(left, field_key)
        right_value = _field_value(right, field_key)
        if left_value and right_value and _normalize_value(left_value) == _normalize_value(right_value):
            return f"same_{field_key}"
    return None


def _document_signature(document: Document) -> str:
    values: List[str] = []
    for field in _latest_fields(document):
        if not field.value:
            continue
        values.append(str(field.value))
    if values:
        return " ".join(values)
    return getattr(document, "filename", "") or ""


def _field_value(document: Document, field_key: str) -> Optional[str]:
    for field in _latest_fields(document):
        if field.field_key == field_key and field.value:
            return str(field.value)
    return None


def _latest_fields(document: Document) -> Iterable[FilledField]:
    for field in getattr(document, "fields", []) or []:
        if getattr(field, "latest", True):
            yield field


def _normalize_value(value: str) -> str:
    return "".join(str(value).casefold().split())


def _text_similarity(left: str, right: str) -> float:
    left_normalized = _normalize_value(left)
    right_normalized = _normalize_value(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return difflib.SequenceMatcher(a=left_normalized, b=right_normalized).ratio()
