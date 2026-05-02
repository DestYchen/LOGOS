from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.enums import DocumentType
from app.mock_services import chatgpt_doc_classifier
from app.services import classification


def _tokens(text: str) -> list[dict[str, str]]:
    return [{"text": part} for part in text.split()]


def test_api_result_wins_before_regex(monkeypatch) -> None:
    monkeypatch.setattr(
        classification,
        "_classify_document_llm",
        lambda tokens, file_name=None: DocumentType.PACKING_LIST,
    )

    result = classification.classify_document(
        _tokens("commercial invoice invoice number 123"),
        file_name="invoice.pdf",
    )

    assert result == DocumentType.PACKING_LIST


def test_unknown_api_result_falls_back_to_regex(monkeypatch) -> None:
    monkeypatch.setattr(
        classification,
        "_classify_document_llm",
        lambda tokens, file_name=None: DocumentType.UNKNOWN,
    )

    result = classification.classify_document(
        _tokens("commercial invoice invoice number 123"),
        file_name="invoice.pdf",
    )

    assert result == DocumentType.INVOICE


def test_api_exception_falls_back_to_regex(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(classification, "_classify_document_llm", _raise)

    result = classification.classify_document(
        _tokens("commercial invoice invoice number 123"),
        file_name="invoice.pdf",
    )

    assert result == DocumentType.INVOICE


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content

    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                )
            ]
        )


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


def test_doc_classifier_returns_normalized_llm_result(monkeypatch) -> None:
    monkeypatch.setattr(chatgpt_doc_classifier, "client", _FakeClient("INVOICE"))
    client = TestClient(chatgpt_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "anything"})

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.INVOICE.value


def test_doc_classifier_invalid_llm_result_returns_unknown(monkeypatch) -> None:
    monkeypatch.setattr(chatgpt_doc_classifier, "client", _FakeClient("not-a-doc-type"))
    client = TestClient(chatgpt_doc_classifier.app)

    response = client.post("/v1/classify", json={"doc_text": "anything"})

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.UNKNOWN.value


def test_doc_classifier_does_not_override_llm_result(monkeypatch) -> None:
    monkeypatch.setattr(chatgpt_doc_classifier, "client", _FakeClient("PACKING_LIST"))
    client = TestClient(chatgpt_doc_classifier.app)

    response = client.post(
        "/v1/classify",
        json={
            "header_text": "commercial invoice invoice number 123",
            "doc_text": "commercial invoice invoice number 123",
        },
    )

    assert response.status_code == 200
    assert response.json()["doc_type"] == DocumentType.PACKING_LIST.value
