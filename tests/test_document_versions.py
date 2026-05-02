from __future__ import annotations

from uuid import uuid4

from app.core.enums import DocumentStatus, DocumentType
from app.models import Document, FilledField
from app.services import document_versions


def _doc(doc_type: DocumentType, filename: str, fields: dict[str, str]) -> Document:
    doc = Document(
        id=uuid4(),
        batch_id=uuid4(),
        filename=filename,
        doc_type=doc_type,
        status=DocumentStatus.FILLED_AUTO,
    )
    doc.fields = [
        FilledField(
            doc_id=doc.id,
            field_key=key,
            value=value,
            latest=True,
            version=1,
        )
        for key, value in fields.items()
    ]
    return doc


def test_mark_alternative_versions_uses_first_invoice_as_primary() -> None:
    first = _doc(
        DocumentType.INVOICE,
        "invoice_a.pdf",
        {"invoice_no": "INV-100", "total_price": "1000"},
    )
    second = _doc(
        DocumentType.INVOICE,
        "invoice_b.pdf",
        {"invoice_no": "INV-100", "total_price": "1001"},
    )

    meta = document_versions.mark_alternative_versions({}, [first, second])

    assert meta["document_versions"][str(first.id)]["version_role"] == "primary"
    second_entry = meta["document_versions"][str(second.id)]
    assert second_entry["version_role"] == "alternative"
    assert second_entry["primary_doc_id"] == str(first.id)
    assert second_entry["reason"] == "same_invoice_no"
    assert document_versions.alternative_document_ids(meta) == {second.id}


def test_mark_alternative_versions_keeps_different_invoice_numbers_primary() -> None:
    first = _doc(DocumentType.INVOICE, "invoice_a.pdf", {"invoice_no": "INV-100"})
    second = _doc(DocumentType.INVOICE, "invoice_b.pdf", {"invoice_no": "INV-200"})

    meta = document_versions.mark_alternative_versions({}, [first, second])

    assert meta["document_versions"][str(first.id)]["version_role"] == "primary"
    assert meta["document_versions"][str(second.id)]["version_role"] == "primary"
    assert document_versions.alternative_document_ids(meta) == set()
