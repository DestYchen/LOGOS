from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook

from app.core.storage import batch_dir


def report_path(batch_id: uuid.UUID) -> Path:
    return batch_dir(str(batch_id)).report / "report.json"


def load_report(batch_id: uuid.UUID) -> Dict[str, Any]:
    path = report_path(batch_id)
    if not path.exists():
        raise FileNotFoundError
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _document_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for document in report.get("documents", []):
        base = {
            "doc_id": document.get("doc_id", ""),
            "filename": document.get("filename", ""),
            "doc_type": document.get("doc_type", ""),
            "status": document.get("status", ""),
        }
        fields = document.get("fields", {}) or {}
        if fields:
            for field_key, field_payload in fields.items():
                payload = field_payload or {}
                rows.append(
                    {
                        **base,
                        "field_key": field_key,
                        "value": payload.get("value"),
                        "confidence": payload.get("confidence"),
                        "source": payload.get("source"),
                        "page": payload.get("page"),
                    }
                )
        else:
            rows.append({**base, "field_key": "", "value": None, "confidence": None, "source": None, "page": None})
    return rows


def _validation_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in report.get("validations", []):
        refs = item.get("refs") or []
        rows.append(
            {
                "rule_id": item.get("rule_id", ""),
                "severity": item.get("severity", ""),
                "message": item.get("message", ""),
                "refs": json.dumps(refs, ensure_ascii=False) if refs else "",
            }
        )
    return rows


def build_report_tables(report: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    return _document_rows(report), _validation_rows(report)


def _write_table(sheet, headers: List[str], rows: List[List[Any]]) -> None:
    sheet.append(headers)
    for row in rows:
        sheet.append(row)


def export_report_excel(report: Dict[str, Any]) -> io.BytesIO:
    document_rows, validation_rows = build_report_tables(report)

    wb = Workbook()
    ws_docs = wb.active
    ws_docs.title = "Documents"
    doc_headers = ["Document ID", "Filename", "Type", "Status", "Field", "Value", "Confidence", "Source", "Page"]
    doc_values = [
        [
            row.get("doc_id"),
            row.get("filename"),
            row.get("doc_type"),
            row.get("status"),
            row.get("field_key"),
            row.get("value"),
            row.get("confidence"),
            row.get("source"),
            row.get("page"),
        ]
        for row in document_rows
    ]
    _write_table(ws_docs, doc_headers, doc_values)

    ws_validations = wb.create_sheet("Validations")
    val_headers = ["Rule", "Severity", "Message", "References"]
    val_values = [
        [row.get("rule_id"), row.get("severity"), row.get("message"), row.get("refs")] for row in validation_rows
    ]
    _write_table(ws_validations, val_headers, val_values)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def export_report_excel_for_batch(batch_id: uuid.UUID) -> io.BytesIO:
    report = load_report(batch_id)
    return export_report_excel(report)
