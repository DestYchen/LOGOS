from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.core.enums import BatchStatus
from app.core.storage import BatchPaths
from app.models import Batch, Document
from app.services import batches


class FakeUpload:
    filename = "invoice.pdf"
    content_type = "application/pdf"

    def __init__(self, content: bytes) -> None:
        self._content = content
        self._read = False

    async def read(self, size: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._content

    async def close(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if isinstance(item, Document) and item.id is None:
                item.id = uuid.uuid4()


def test_save_documents_records_split_page_source_metadata(tmp_path: Path, monkeypatch) -> None:
    batch = Batch(id=uuid.uuid4(), status=BatchStatus.NEW, meta={})
    paths = BatchPaths(base=tmp_path)
    paths.ensure()

    monkeypatch.setattr(batches, "batch_dir", lambda batch_id: paths)
    monkeypatch.setattr(batches, "_generate_pdf_preview", lambda *args, **kwargs: None)

    def fake_split_pdf_file(source: Path, target_dir: Path, base_name: str):
        page_1 = target_dir / "invoice_p1.pdf"
        page_2 = target_dir / "invoice_p2.pdf"
        page_1.write_bytes(b"page 1")
        page_2.write_bytes(b"page 2")
        return [page_1, page_2]

    monkeypatch.setattr(batches, "_split_pdf_file", fake_split_pdf_file)

    asyncio.run(batches.save_documents(FakeSession(), batch, [FakeUpload(b"%PDF")]))

    source_pages = batch.meta["source_pages"]
    assert len(source_pages) == 2
    entries = sorted(source_pages.values(), key=lambda item: item["page_index"])
    assert entries == [
        {"source_group": "invoice", "page_index": 1, "page_count": 2},
        {"source_group": "invoice", "page_index": 2, "page_count": 2},
    ]
