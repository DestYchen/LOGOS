from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.mock_services import openclaw_doc_assembler


def test_openclaw_doc_assembler_parses_grouping(monkeypatch) -> None:
    async def fake_call_openclaw(prompt: str) -> str:
        return json.dumps(
            {
                "groups": [
                    {
                        "final_doc_type": "INVOICE",
                        "page_doc_ids": ["doc-1", "doc-2"],
                        "confidence": 0.8,
                        "reason": "same invoice continues",
                    }
                ]
            }
        )

    monkeypatch.setattr(openclaw_doc_assembler, "_call_openclaw", fake_call_openclaw)
    client = TestClient(openclaw_doc_assembler.app)

    response = client.post(
        "/v1/assemble",
        json={
            "batch_id": "batch-1",
            "pages": [
                {
                    "doc_id": "doc-1",
                    "filename": "invoice_p1.pdf",
                    "source_group": "invoice",
                    "page_index": 1,
                    "doc_type": "INVOICE",
                    "doc_text": "invoice first page",
                },
                {
                    "doc_id": "doc-2",
                    "filename": "invoice_p2.pdf",
                    "source_group": "invoice",
                    "page_index": 2,
                    "doc_type": "QUALITY_CERTIFICATE",
                    "doc_text": "continued goods table",
                },
            ],
        },
    )

    assert response.status_code == 200
    groups = response.json()["groups"]
    assert len(groups) == 1
    assert groups[0]["final_doc_type"] == "INVOICE"
    assert groups[0]["page_doc_ids"] == ["doc-1", "doc-2"]


def test_openclaw_doc_assembler_invalid_json_falls_back_to_single_pages(monkeypatch) -> None:
    async def fake_call_openclaw(prompt: str) -> str:
        return "not json"

    monkeypatch.setattr(openclaw_doc_assembler, "_call_openclaw", fake_call_openclaw)
    client = TestClient(openclaw_doc_assembler.app)

    response = client.post(
        "/v1/assemble",
        json={
            "batch_id": "batch-1",
            "pages": [
                {
                    "doc_id": "doc-1",
                    "filename": "a_p1.pdf",
                    "source_group": "a",
                    "page_index": 1,
                    "doc_type": "INVOICE",
                },
                {
                    "doc_id": "doc-2",
                    "filename": "a_p2.pdf",
                    "source_group": "a",
                    "page_index": 2,
                    "doc_type": "INVOICE",
                },
            ],
        },
    )

    assert response.status_code == 200
    groups = response.json()["groups"]
    assert [group["page_doc_ids"] for group in groups] == [["doc-1"], ["doc-2"]]


def test_openclaw_doc_assembler_never_groups_different_sources(monkeypatch) -> None:
    async def fake_call_openclaw(prompt: str) -> str:
        return json.dumps({"groups": [{"final_doc_type": "INVOICE", "page_doc_ids": ["doc-1", "doc-2"]}]})

    monkeypatch.setattr(openclaw_doc_assembler, "_call_openclaw", fake_call_openclaw)
    client = TestClient(openclaw_doc_assembler.app)

    response = client.post(
        "/v1/assemble",
        json={
            "batch_id": "batch-1",
            "pages": [
                {
                    "doc_id": "doc-1",
                    "filename": "a_p1.pdf",
                    "source_group": "a",
                    "page_index": 1,
                    "doc_type": "INVOICE",
                },
                {
                    "doc_id": "doc-2",
                    "filename": "b_p1.pdf",
                    "source_group": "b",
                    "page_index": 1,
                    "doc_type": "INVOICE",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert [group["page_doc_ids"] for group in response.json()["groups"]] == [["doc-1"], ["doc-2"]]
