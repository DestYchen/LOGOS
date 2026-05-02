from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from app.core.enums import DocumentStatus, DocumentType
from app.core.storage import BatchPaths
from app.models import Batch, Document
from app.services import pipeline


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.deleted = []

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None

    async def delete(self, item) -> None:
        self.deleted.append(item)


def test_source_page_info_uses_batch_meta() -> None:
    doc_id = uuid.uuid4()
    batch = Batch(id=uuid.uuid4(), meta={"source_pages": {str(doc_id): {"source_group": "invoice", "page_index": 2, "page_count": 3}}})
    document = Document(id=doc_id, batch_id=batch.id, filename="anything.pdf", pages=1)

    info = pipeline._source_page_info(batch, document)

    assert info == {"source_group": "invoice", "page_index": 2, "page_count": 3}


def test_source_page_info_infers_split_filename() -> None:
    batch = Batch(id=uuid.uuid4(), meta={})
    document = Document(id=uuid.uuid4(), batch_id=batch.id, filename="invoice_p12.pdf", pages=1)

    info = pipeline._source_page_info(batch, document)

    assert info["source_group"] == "invoice"
    assert info["page_index"] == 12


def test_merge_assembled_groups_creates_merged_document(tmp_path: Path, monkeypatch) -> None:
    batch = Batch(id=uuid.uuid4(), meta={"processing_run": {"mode": "initial_upload", "doc_ids": []}, "source_pages": {}})
    paths = BatchPaths(base=tmp_path)
    paths.ensure()

    doc1 = _make_text_ready_doc(batch, "invoice_p1.pdf", "p0_t0", "hello")
    doc2 = _make_text_ready_doc(batch, "invoice_p2.pdf", "p0_t0", "world")
    batch.documents.extend([doc1, doc2])
    batch.meta["processing_run"]["doc_ids"] = [str(doc1.id), str(doc2.id)]
    batch.meta["source_pages"] = {
        str(doc1.id): {"source_group": "invoice", "page_index": 1, "page_count": 2},
        str(doc2.id): {"source_group": "invoice", "page_index": 2, "page_count": 2},
    }
    _write_doc_files(paths, doc1, "hello")
    _write_doc_files(paths, doc2, "world")

    async def _fake_get_dots_bbox_tokens(**kwargs):
        doc_id = kwargs["doc_id"]
        if doc_id == doc1.id:
            return [{"id": "p0_t0", "text": "hello", "page": 1, "bbox": [1, 2, 3, 4]}]
        if doc_id == doc2.id:
            return [{"id": "p0_t0", "text": "world", "page": 1, "bbox": [5, 6, 7, 8]}]
        return []

    monkeypatch.setattr(pipeline.field_bbox_grounder, "enabled", lambda: True)
    monkeypatch.setattr(pipeline.field_bbox_grounder, "get_dots_bbox_tokens", _fake_get_dots_bbox_tokens)

    session = FakeSession()
    asyncio.run(
        pipeline._merge_assembled_groups(
            session,
            batch,
            paths,
            [
                {
                    "final_doc_type": DocumentType.INVOICE.value,
                    "page_doc_ids": [str(doc1.id), str(doc2.id)],
                }
            ],
        )
    )

    assert len(batch.documents) == 1
    merged = batch.documents[0]
    assert merged.doc_type == DocumentType.INVOICE
    assert merged.status == DocumentStatus.TEXT_READY
    assert merged.pages == 2
    assert merged.filename.startswith("assembled_invoice_")
    assert session.deleted == [doc1, doc2]

    ocr_payload = json.loads((paths.base / merged.ocr_path).read_text(encoding="utf-8"))
    assert [token["text"] for token in ocr_payload["tokens"]] == ["hello", "world"]
    assert [token["page"] for token in ocr_payload["tokens"]] == [1, 2]
    assert [token["id"] for token in ocr_payload["tokens"]] == ["p0_t0", "p1_t0"]
    bbox_payload = json.loads(
        (paths.derived_for(str(merged.id)) / pipeline.field_bbox_grounder.DOTS_BBOX_OCR_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert [token["text"] for token in bbox_payload["tokens"]] == ["hello", "world"]
    assert [token["page"] for token in bbox_payload["tokens"]] == [1, 2]
    assert [token["id"] for token in bbox_payload["tokens"]] == ["p0_t0", "p1_t0"]
    assert batch.meta["processing_run"]["doc_ids"] == [str(merged.id)]


def _make_text_ready_doc(batch: Batch, filename: str, token_id: str, text: str) -> Document:
    doc_id = uuid.uuid4()
    return Document(
        id=doc_id,
        batch_id=batch.id,
        filename=filename,
        mime="application/pdf",
        doc_type=DocumentType.INVOICE,
        status=DocumentStatus.TEXT_READY,
        pages=1,
        ocr_path=f"derived/{doc_id}/ocr.json",
    )


def _write_doc_files(paths: BatchPaths, document: Document, text: str) -> None:
    (paths.raw / document.filename).write_text(text, encoding="utf-8")
    derived = paths.derived_for(str(document.id))
    (derived / "ocr.json").write_text(
        json.dumps(
            {
                "doc_id": str(document.id),
                "tokens": [
                    {
                        "id": "p0_t0",
                        "text": text,
                        "conf": 1.0,
                        "bbox": [0, 0, 0, 0],
                        "page": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
