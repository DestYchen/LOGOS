from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.enums import DocumentType
from app.mock_services import openclaw_json_filler


def test_openclaw_json_filler_valid_json_fills_template(monkeypatch) -> None:
    async def _fake_call_openclaw(prompt: str) -> str:
        return json.dumps(
            {
                "fields": {
                    "invoice_no": {
                        "value": "INV-1",
                        "token_refs": ["t1"],
                        "bbox": [1, 2, 3, 4],
                        "page": 2,
                    }
                }
            }
        )

    monkeypatch.setattr(openclaw_json_filler, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_json_filler.app)

    response = client.post(
        "/v1/fill",
        json={
            "doc_id": "doc-1",
            "doc_type": DocumentType.INVOICE.value,
            "doc_text": "invoice INV-1",
            "tokens": [{"id": "t1", "text": "INV-1"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["doc_id"] == "doc-1"
    assert payload["doc_type"] == DocumentType.INVOICE.value
    assert payload["fields"]["invoice_no"]["value"] == "INV-1"
    assert payload["fields"]["invoice_no"]["token_refs"] == ["t1"]
    assert payload["fields"]["invoice_no"]["bbox"] == [1, 2, 3, 4]
    assert payload["fields"]["invoice_no"]["page"] == 2
    assert payload["fields"]["invoice_no"]["source"] == "llm"


def test_openclaw_json_filler_invalid_json_returns_empty_template(monkeypatch) -> None:
    async def _fake_call_openclaw(prompt: str) -> str:
        return "not json"

    monkeypatch.setattr(openclaw_json_filler, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_json_filler.app)

    response = client.post(
        "/v1/fill",
        json={
            "doc_id": "doc-2",
            "doc_type": DocumentType.INVOICE.value,
            "doc_text": "invoice text",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["fields"]["invoice_no"]["value"] == ""
    assert payload["fields"]["invoice_no"]["token_refs"] == []
    assert payload["fields"]["invoice_no"]["bbox"] == []
    assert payload["fields"]["invoice_no"]["page"] is None
    assert payload["fields"]["invoice_no"]["source"] == "llm"
    assert payload["meta"]["parsed"] is True


def test_openclaw_json_filler_preserves_missing_fields(monkeypatch) -> None:
    async def _fake_call_openclaw(prompt: str) -> str:
        return '{"fields": {"invoice_no": {"value": "INV-2"}}}'

    monkeypatch.setattr(openclaw_json_filler, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_json_filler.app)

    response = client.post(
        "/v1/fill",
        json={
            "doc_id": "doc-3",
            "doc_type": DocumentType.INVOICE.value,
            "doc_text": "invoice INV-2",
        },
    )

    assert response.status_code == 200
    fields = response.json()["fields"]
    assert fields["invoice_no"]["value"] == "INV-2"
    assert "invoice_date" in fields
    assert fields["invoice_date"]["value"] == ""
    assert fields["invoice_date"]["token_refs"] == []


def test_openclaw_json_filler_salvages_fenced_json(monkeypatch) -> None:
    async def _fake_call_openclaw(prompt: str) -> str:
        return '```json\n{"fields": {"invoice_no": {"value": "INV-3"}}}\n```'

    monkeypatch.setattr(openclaw_json_filler, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_json_filler.app)

    response = client.post(
        "/v1/fill",
        json={
            "doc_id": "doc-4",
            "doc_type": DocumentType.INVOICE.value,
            "doc_text": "invoice INV-3",
        },
    )

    assert response.status_code == 200
    assert response.json()["fields"]["invoice_no"]["value"] == "INV-3"


def test_openclaw_json_filler_adds_product_defaults(monkeypatch) -> None:
    async def _fake_call_openclaw(prompt: str) -> str:
        return json.dumps(
            {
                "fields": {
                    "products": {
                        "product_1": {
                            "name_product": {
                                "value": "HOKI",
                                "token_refs": ["p1_t1"],
                            }
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(openclaw_json_filler, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_json_filler.app)

    response = client.post(
        "/v1/fill",
        json={
            "doc_id": "doc-5",
            "doc_type": DocumentType.INVOICE.value,
            "doc_text": "HOKI",
        },
    )

    assert response.status_code == 200
    product = response.json()["fields"]["products"]["product_1"]
    assert product["name_product"]["value"] == "HOKI"
    assert product["name_product"]["bbox"] == []
    assert product["name_product"]["page"] is None
    assert product["name_product"]["source"] == "llm"


def test_openclaw_json_filler_prompt_includes_product_template(monkeypatch) -> None:
    prompts = []

    async def _fake_call_openclaw(prompt: str) -> str:
        prompts.append(prompt)
        return '{"fields": {"products": {}}}'

    monkeypatch.setattr(openclaw_json_filler, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_json_filler.app)

    response = client.post(
        "/v1/fill",
        json={
            "doc_id": "doc-6",
            "doc_type": DocumentType.SPECIFICATION.value,
            "doc_text": "1 FROZEN OILFISH 40 22,787.68",
        },
    )

    assert response.status_code == 200
    assert "PRODUCT TEMPLATE:" in prompts[0]
    assert "products.product_1" in prompts[0]
    assert "price_per_unit" in prompts[0]
