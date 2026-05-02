from __future__ import annotations

import asyncio
import json
import uuid

from app.core.enums import DocumentType
from app.services import field_bbox_grounder


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(field_bbox_grounder.settings, "field_bbox_grounding_enabled", True)
    monkeypatch.setattr(field_bbox_grounder.settings, "field_bbox_grounding_openclaw_api_key", "token")


def test_ground_fields_preserves_values_and_adds_bbox(monkeypatch) -> None:
    _enable(monkeypatch)

    async def _fake_call_openclaw(prompt: str) -> str:
        return json.dumps(
            {
                "fields": {
                    "invoice_no": {
                        "value": "CHANGED",
                        "token_refs": ["p0_t0"],
                    }
                }
            }
        )

    monkeypatch.setattr(field_bbox_grounder, "_call_openclaw", _fake_call_openclaw)
    fields = {"invoice_no": {"value": "INV-1", "bbox": [99, 99, 99, 99], "token_refs": ["old"]}}
    tokens = [{"id": "p0_t0", "text": "INV-1", "page": 1, "bbox": [10, 20, 30, 40]}]

    changed = asyncio.run(
        field_bbox_grounder.ground_fields(
            doc_id=uuid.uuid4(),
            doc_type=DocumentType.INVOICE,
            file_name="invoice.pdf",
            fields=fields,
            dots_tokens=tokens,
        )
    )

    assert changed is True
    assert fields["invoice_no"]["value"] == "INV-1"
    assert fields["invoice_no"]["token_refs"] == ["p0_t0"]
    assert fields["invoice_no"]["page"] == 1
    assert fields["invoice_no"]["bbox"] == [10.0, 20.0, 30.0, 40.0]


def test_ground_fields_invalid_refs_leave_bbox_empty(monkeypatch) -> None:
    _enable(monkeypatch)

    async def _fake_call_openclaw(prompt: str) -> str:
        return '{"fields": {"invoice_no": {"token_refs": ["missing"]}}}'

    monkeypatch.setattr(field_bbox_grounder, "_call_openclaw", _fake_call_openclaw)
    fields = {"invoice_no": {"value": "INV-1", "bbox": [1, 2, 3, 4], "token_refs": ["old"]}}
    tokens = [{"id": "p0_t0", "text": "INV-1", "page": 1, "bbox": [10, 20, 30, 40]}]

    changed = asyncio.run(
        field_bbox_grounder.ground_fields(
            doc_id=uuid.uuid4(),
            doc_type=DocumentType.INVOICE,
            file_name="invoice.pdf",
            fields=fields,
            dots_tokens=tokens,
        )
    )

    assert changed is False
    assert fields["invoice_no"]["value"] == "INV-1"
    assert fields["invoice_no"]["token_refs"] == []
    assert fields["invoice_no"]["bbox"] == []


def test_ground_fields_handles_product_field_refs(monkeypatch) -> None:
    _enable(monkeypatch)

    async def _fake_call_openclaw(prompt: str) -> str:
        return '{"fields": {"products.product_1.name_product": {"token_refs": ["p0_t2"]}}}'

    monkeypatch.setattr(field_bbox_grounder, "_call_openclaw", _fake_call_openclaw)
    fields = {"products.product_1.name_product": {"value": "HOKI", "bbox": [], "token_refs": []}}
    tokens = [{"id": "p0_t2", "text": "HOKI", "page": 2, "bbox": [50, 60, 150, 80], "category": "Table"}]

    changed = asyncio.run(
        field_bbox_grounder.ground_fields(
            doc_id=uuid.uuid4(),
            doc_type=DocumentType.SPECIFICATION,
            file_name="spec.pdf",
            fields=fields,
            dots_tokens=tokens,
        )
    )

    assert changed is True
    assert fields["products.product_1.name_product"]["token_refs"] == ["p0_t2"]
    assert fields["products.product_1.name_product"]["page"] == 2
    assert fields["products.product_1.name_product"]["bbox"] == [50.0, 60.0, 150.0, 80.0]


def test_read_write_cached_tokens(tmp_path) -> None:
    cache_file = tmp_path / field_bbox_grounder.DOTS_BBOX_OCR_FILENAME
    doc_id = uuid.uuid4()
    field_bbox_grounder.write_cached_tokens(
        cache_file=cache_file,
        doc_id=doc_id,
        tokens=[{"id": "p0_t0", "text": "A", "page": 1, "bbox": [1, 2, 3, 4]}],
    )

    tokens = field_bbox_grounder.read_cached_tokens(cache_file)

    assert tokens == [
        {
            "id": "p0_t0",
            "text": "A",
            "page": 1,
            "bbox": [1, 2, 3, 4],
            "category": "Text",
            "conf": 0.0,
        }
    ]
