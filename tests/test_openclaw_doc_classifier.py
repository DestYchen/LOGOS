from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.enums import DocumentType
from app.mock_services import openclaw_doc_classifier


def test_openclaw_doc_classifier_returns_normalized_type(monkeypatch) -> None:
    async def _fake_call_openclaw(**kwargs) -> str:
        return "INVOICE"

    monkeypatch.setattr(openclaw_doc_classifier, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_id": "doc-1", "doc_text": "invoice text"})

    assert response.status_code == 200
    assert response.json() == {"doc_id": "doc-1", "doc_type": DocumentType.INVOICE.value}


def test_openclaw_doc_classifier_invalid_type_returns_unknown(monkeypatch) -> None:
    async def _fake_call_openclaw(**kwargs) -> str:
        return "not-a-document-type"

    monkeypatch.setattr(openclaw_doc_classifier, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "unknown text"})

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.UNKNOWN.value


def test_openclaw_doc_classifier_plain_contract_returns_unknown(monkeypatch) -> None:
    async def _fake_call_openclaw(**kwargs) -> str:
        return "CONTRACT"

    monkeypatch.setattr(openclaw_doc_classifier, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "contract text"})

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.UNKNOWN.value


def test_openclaw_doc_classifier_strips_wrapping(monkeypatch) -> None:
    async def _fake_call_openclaw(**kwargs) -> str:
        return "  `PACKING_LIST`  \nextra ignored text"

    monkeypatch.setattr(openclaw_doc_classifier, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "packing list"})

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.PACKING_LIST.value


def test_openclaw_doc_classifier_allows_contract_parts(monkeypatch) -> None:
    async def _fake_call_openclaw(**kwargs) -> str:
        return "CONTRACT_2"

    monkeypatch.setattr(openclaw_doc_classifier, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "payment terms"})

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.CONTRACT_2.value


def test_openclaw_doc_classifier_truncates_long_text(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def _fake_call_openclaw(**kwargs) -> str:
        captured["doc_text"] = kwargs["doc_text"]
        return "UNKNOWN"

    monkeypatch.setattr(openclaw_doc_classifier, "OPENCLAW_CLASSIFIER_MAX_TEXT_CHARS", 5)
    monkeypatch.setattr(openclaw_doc_classifier, "_call_openclaw", _fake_call_openclaw)
    client = TestClient(openclaw_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "123456789"})

    assert response.status_code == 200
    assert captured["doc_text"] == "12345"
