from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import pytest

from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.models import Batch, Document, FilledField
from app.services import product_matrix, reporting
from app.core.storage import BatchPaths


def _doc_payload(
    doc_type: str,
    *,
    filename: str | None = None,
    doc_id: str | None = None,
    fields: Dict[str, str | None] | None = None,
) -> Dict[str, Any]:
    payload_fields: Dict[str, Dict[str, Any]] = {}
    for key, value in (fields or {}).items():
        payload_fields[key] = {"value": value, "confidence": 0.95}
    return {
        "doc_id": doc_id or str(uuid4()),
        "filename": filename or f"{doc_type.lower()}.pdf",
        "doc_type": doc_type,
        "status": DocumentStatus.FILLED_AUTO.value,
        "fields": payload_fields,
    }


def _field(doc_id, field_key: str, value: str | None, *, confidence: float = 0.95) -> FilledField:
    return FilledField(
        doc_id=doc_id,
        field_key=field_key,
        value=value,
        confidence=confidence,
        source="ocr",
        latest=True,
        version=1,
    )


def test_product_matrix_orders_rows_by_profile_and_batch_order() -> None:
    packing_list = _doc_payload(
        DocumentType.PACKING_LIST.value,
        doc_id="packing",
        fields={
            "products.product_1.packages": "1000",
            "products.product_1.net_weight": "2000",
            "products.product_1.net_weight_with_glaze": "2100",
            "products.product_1.net_weight_with_ice": "2200",
            "products.product_1.net_weight_with_glaze_and_pack": "2300",
            "products.product_1.gross_weight": "2400",
        },
    )
    price_list_a = _doc_payload(
        DocumentType.PRICE_LIST_1.value,
        doc_id="price-a",
        fields={"products.product_1.packages": "10"},
    )
    price_list_b = _doc_payload(
        DocumentType.PRICE_LIST_1.value,
        doc_id="price-b",
        fields={"products.product_1.packages": "20"},
    )
    form_a = _doc_payload(
        DocumentType.FORM_A.value,
        doc_id="form-a",
        fields={
            "products.product_1.packages": "30",
            "products.product_1.net_weight": "40",
            "products.product_1.gross_weight": "50",
        },
    )
    contract = _doc_payload(DocumentType.CONTRACT.value, doc_id="contract", fields={"contract_no": "A-1"})

    columns, rows = product_matrix.build_product_matrix(
        [price_list_a, contract, packing_list, price_list_b, form_a],
        document_profile="standard",
    )

    assert [column["key"] for column in columns] == [field for field, _ in product_matrix.PRODUCT_SUM_FIELDS]
    assert [row["doc_id"] for row in rows] == ["packing", "price-a", "price-b", "form-a"]


def test_product_matrix_marks_supported_and_unsupported_cells_from_schema() -> None:
    form_a = _doc_payload(
        DocumentType.FORM_A.value,
        doc_id="form-a",
        fields={
            "products.product_1.packages": "30",
            "products.product_1.net_weight": "40",
            "products.product_1.gross_weight": "50",
        },
    )

    _, rows = product_matrix.build_product_matrix([form_a], document_profile="standard")

    row = rows[0]
    assert row["cells"]["packages"]["supported"] is True
    assert row["cells"]["net_weight"]["supported"] is True
    assert row["cells"]["gross_weight"]["supported"] is True
    assert row["cells"]["net_weight_with_glaze"]["supported"] is False
    assert row["cells"]["net_weight_with_glaze"]["status"] is None


def test_product_matrix_uses_packing_list_as_anchor_for_matches_and_mismatches() -> None:
    packing_list = _doc_payload(
        DocumentType.PACKING_LIST.value,
        doc_id="packing",
        fields={
            "products.product_1.packages": "1,000",
            "products.product_2.packages": "22",
            "products.product_1.net_weight": "20,000",
            "products.product_2.net_weight": "440",
            "products.product_1.net_weight_with_glaze": "20,500",
            "products.product_2.net_weight_with_glaze": "451",
            "products.product_1.net_weight_with_ice": "20,700",
            "products.product_2.net_weight_with_ice": "455",
            "products.product_1.net_weight_with_glaze_and_pack": "20,900",
            "products.product_2.net_weight_with_glaze_and_pack": "460",
            "products.product_1.gross_weight": "21,000",
            "products.product_2.gross_weight": "470",
        },
    )
    proforma = _doc_payload(
        DocumentType.PROFORMA.value,
        doc_id="proforma",
        fields={
            "products.product_1.packages": "1000",
            "products.product_2.packages": "20",
            "products.product_1.net_weight": "20,000",
            "products.product_2.net_weight": "440",
            "products.product_1.gross_weight": "21,000",
            "products.product_2.gross_weight": "470",
        },
    )
    quality_certificate = _doc_payload(
        DocumentType.QUALITY_CERTIFICATE.value,
        doc_id="quality",
        fields={
            "products.product_1.packages": "1000",
            "products.product_2.packages": "22",
            "products.product_1.net_weight": "20,000",
            "products.product_2.net_weight": "440",
            "products.product_1.gross_weight": "21,000",
            "products.product_2.gross_weight": "470",
        },
    )

    _, rows = product_matrix.build_product_matrix(
        [quality_certificate, proforma, packing_list],
        document_profile="standard",
    )

    by_id = {row["doc_id"]: row for row in rows}
    assert by_id["packing"]["cells"]["packages"]["status"] == "anchor"
    assert by_id["quality"]["cells"]["packages"]["status"] == "match"
    assert by_id["proforma"]["cells"]["packages"]["status"] == "mismatch"
    assert by_id["quality"]["cells"]["packages"]["value"] == "1022"
    assert by_id["proforma"]["cells"]["packages"]["value"] == "1020"


def test_product_matrix_marks_supported_cells_missing_without_packing_list_anchor() -> None:
    proforma = _doc_payload(
        DocumentType.PROFORMA.value,
        doc_id="proforma",
        fields={
            "products.product_1.packages": "10",
            "products.product_1.net_weight": "20",
            "products.product_1.gross_weight": "22",
        },
    )

    _, rows = product_matrix.build_product_matrix([proforma], document_profile="standard")

    row = rows[0]
    assert row["cells"]["packages"]["status"] == "missing"
    assert row["cells"]["net_weight"]["status"] == "missing"
    assert row["cells"]["gross_weight"]["status"] == "missing"


def test_product_matrix_uses_first_packing_list_as_anchor_when_multiple_are_present() -> None:
    first = _doc_payload(
        DocumentType.PACKING_LIST.value,
        doc_id="packing-1",
        fields={
            "products.product_1.packages": "100",
            "products.product_1.net_weight": "200",
            "products.product_1.net_weight_with_glaze": "210",
            "products.product_1.net_weight_with_ice": "220",
            "products.product_1.net_weight_with_glaze_and_pack": "230",
            "products.product_1.gross_weight": "240",
        },
    )
    second = _doc_payload(
        DocumentType.PACKING_LIST.value,
        doc_id="packing-2",
        fields={
            "products.product_1.packages": "101",
            "products.product_1.net_weight": "200",
            "products.product_1.net_weight_with_glaze": "210",
            "products.product_1.net_weight_with_ice": "220",
            "products.product_1.net_weight_with_glaze_and_pack": "230",
            "products.product_1.gross_weight": "240",
        },
    )

    _, rows = product_matrix.build_product_matrix([first, second], document_profile="standard")

    by_id = {row["doc_id"]: row for row in rows}
    assert by_id["packing-1"]["cells"]["packages"]["status"] == "anchor"
    assert by_id["packing-2"]["cells"]["packages"]["status"] == "mismatch"


def test_product_matrix_marks_partial_or_unparseable_aggregates_missing() -> None:
    packing_list = _doc_payload(
        DocumentType.PACKING_LIST.value,
        doc_id="packing",
        fields={
            "products.product_1.packages": "10",
            "products.product_1.net_weight": "20",
            "products.product_1.net_weight_with_glaze": "21",
            "products.product_1.net_weight_with_ice": "22",
            "products.product_1.net_weight_with_glaze_and_pack": "23",
            "products.product_1.gross_weight": "24",
        },
    )
    veterinary_certificate = _doc_payload(
        DocumentType.VETERINARY_CERTIFICATE.value,
        doc_id="vet",
        fields={
            "products.product_1.packages": "5; 5",
            "products.product_2.packages": None,
            "products.product_1.net_weight": "10; 10",
            "products.product_2.net_weight": "abc",
        },
    )

    _, rows = product_matrix.build_product_matrix(
        [packing_list, veterinary_certificate],
        document_profile="standard",
    )

    row = next(item for item in rows if item["doc_id"] == "vet")
    assert row["cells"]["packages"]["status"] == "missing"
    assert row["cells"]["net_weight"]["status"] == "missing"


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1,022", "1022"),
        ("22,687.500 KGS", "22687.5"),
        ("20.625,00", "20625"),
        ("10; 20; 30", "60"),
        ("1 000; 22", "1022"),
        ("1.234.567", "1234567"),
    ],
)
def test_decimal_parser_handles_common_weight_and_package_formats(raw_value: str, expected: str) -> None:
    parsed = product_matrix._parse_semicolon_sum(raw_value)

    assert parsed is not None
    assert product_matrix._decimal_to_string(parsed) == expected


@pytest.mark.asyncio
async def test_generate_report_persists_product_matrix_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    batch = Batch(id=uuid4(), status=BatchStatus.VALIDATED, meta={"document_profile": "standard"})

    packing_doc = Document(
        id=uuid4(),
        batch_id=batch.id,
        filename="packing_list.pdf",
        doc_type=DocumentType.PACKING_LIST,
        status=DocumentStatus.FILLED_AUTO,
    )
    packing_doc.fields = [
        _field(packing_doc.id, "products.product_1.packages", "1000"),
        _field(packing_doc.id, "products.product_1.net_weight", "2000"),
        _field(packing_doc.id, "products.product_1.net_weight_with_glaze", "2100"),
        _field(packing_doc.id, "products.product_1.net_weight_with_ice", "2200"),
        _field(packing_doc.id, "products.product_1.net_weight_with_glaze_and_pack", "2300"),
        _field(packing_doc.id, "products.product_1.gross_weight", "2400"),
    ]

    proforma_doc = Document(
        id=uuid4(),
        batch_id=batch.id,
        filename="proforma.pdf",
        doc_type=DocumentType.PROFORMA,
        status=DocumentStatus.FILLED_AUTO,
    )
    proforma_doc.fields = [
        _field(proforma_doc.id, "products.product_1.packages", "1000"),
        _field(proforma_doc.id, "products.product_1.net_weight", "2000"),
        _field(proforma_doc.id, "products.product_1.gross_weight", "2400"),
    ]

    batch.documents = [proforma_doc, packing_doc]

    async def fake_load_batch_with_fields(session, batch_id):
        return batch

    async def fake_fetch_validations(session, batch_id):
        return []

    monkeypatch.setattr(reporting, "load_batch_with_fields", fake_load_batch_with_fields)
    monkeypatch.setattr(reporting, "fetch_validations", fake_fetch_validations)
    monkeypatch.setattr(reporting, "batch_dir", lambda batch_id: BatchPaths(base=tmp_path / str(batch_id)))

    payload = await reporting.generate_report(object(), batch.id)

    report_file = tmp_path / str(batch.id) / "report" / "report.json"
    assert report_file.exists()
    stored = json.loads(report_file.read_text(encoding="utf-8"))

    assert payload["product_matrix_columns"]
    assert payload["product_matrix"]
    assert stored["product_matrix_columns"]
    assert stored["product_matrix"]
    assert stored["product_matrix"][0]["cells"]["packages"]["status"] in {"anchor", "match", "mismatch", "missing"}


@pytest.mark.asyncio
async def test_generate_report_excludes_alternative_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary_id = uuid4()
    alternative_id = uuid4()
    batch = Batch(
        id=uuid4(),
        status=BatchStatus.VALIDATED,
        meta={
            "document_profile": "standard",
            "document_versions": {
                str(primary_id): {"version_role": "primary", "duplicate_group_id": "invoice_1"},
                str(alternative_id): {
                    "version_role": "alternative",
                    "primary_doc_id": str(primary_id),
                    "duplicate_group_id": "invoice_1",
                },
            },
        },
    )

    primary_doc = Document(
        id=primary_id,
        batch_id=batch.id,
        filename="invoice_a.pdf",
        doc_type=DocumentType.INVOICE,
        status=DocumentStatus.FILLED_AUTO,
    )
    primary_doc.fields = [_field(primary_doc.id, "invoice_no", "INV-1")]
    alternative_doc = Document(
        id=alternative_id,
        batch_id=batch.id,
        filename="invoice_b.pdf",
        doc_type=DocumentType.INVOICE,
        status=DocumentStatus.FILLED_AUTO,
    )
    alternative_doc.fields = [_field(alternative_doc.id, "invoice_no", "INV-1")]
    batch.documents = [primary_doc, alternative_doc]

    async def fake_load_batch_with_fields(session, batch_id):
        return batch

    async def fake_fetch_validations(session, batch_id):
        return []

    monkeypatch.setattr(reporting, "load_batch_with_fields", fake_load_batch_with_fields)
    monkeypatch.setattr(reporting, "fetch_validations", fake_fetch_validations)
    monkeypatch.setattr(reporting, "batch_dir", lambda batch_id: BatchPaths(base=tmp_path / str(batch_id)))

    payload = await reporting.generate_report(object(), batch.id)

    assert [document["doc_id"] for document in payload["documents"]] == [str(primary_id)]
    assert [document["doc_id"] for document in payload["alternative_documents"]] == [str(alternative_id)]
