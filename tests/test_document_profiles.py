from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas import ConfirmPrepRequest
from app.core.document_profiles import (
    DEFAULT_DOCUMENT_PROFILE,
    get_active_document_type_values,
    get_document_profile,
    get_expected_doc_types,
    get_field_matrix_doc_types,
)


def test_standard_profile_contains_full_default_set() -> None:
    expected = get_expected_doc_types(DEFAULT_DOCUMENT_PROFILE)

    assert [entry["display_key"] for entry in expected] == [
        "CONTRACT",
        "ADDENDUM",
        "PROFORMA",
        "INVOICE",
        "BILL_OF_LADING",
        "CMR",
        "PACKING_LIST",
        "PRICE_LIST_1",
        "PRICE_LIST_2",
        "QUALITY_CERTIFICATE",
        "VETERINARY_CERTIFICATE",
        "EXPORT_DECLARATION",
        "SPECIFICATION",
        "CERTIFICATE_OF_ORIGIN",
        "FORM_A",
        "EAV",
        "CT-3",
        "T1",
    ]


def test_china_profile_excludes_non_required_transport_documents() -> None:
    expected = get_expected_doc_types("china_sea")
    display_keys = [entry["display_key"] for entry in expected]

    assert display_keys == [
        "CONTRACT",
        "ADDENDUM",
        "PROFORMA",
        "BILL_OF_LADING",
        "PACKING_LIST",
        "INVOICE",
        "PRICE_LIST_1",
        "PRICE_LIST_2",
        "VETERINARY_CERTIFICATE",
        "QUALITY_CERTIFICATE",
        "CERTIFICATE_OF_ORIGIN",
        "EXPORT_DECLARATION",
        "SPECIFICATION",
    ]
    assert "CMR" not in display_keys
    assert "FORM_A" not in display_keys
    assert "EAV" not in display_keys
    assert "CT-3" not in display_keys
    assert "T1" not in display_keys


def test_addendum_remains_placeholder_without_actual_type() -> None:
    addendum = next(entry for entry in get_expected_doc_types("china_sea") if entry["display_key"] == "ADDENDUM")

    assert addendum["actual_type"] is None


def test_field_matrix_doc_types_follow_profile_and_skip_addendum_placeholder() -> None:
    standard = get_field_matrix_doc_types(DEFAULT_DOCUMENT_PROFILE)
    china = get_field_matrix_doc_types("china_sea")

    assert "ADDENDUM" not in standard
    assert "ADDENDUM" not in china
    assert "CMR" in standard
    assert "CMR" not in china


def test_document_profile_falls_back_to_standard() -> None:
    assert get_document_profile(None) == DEFAULT_DOCUMENT_PROFILE
    assert get_document_profile({"document_profile": "unknown"}) == DEFAULT_DOCUMENT_PROFILE
    assert get_document_profile({"document_profile": "china_sea"}) == "china_sea"


def test_active_document_types_for_china_exclude_removed_types() -> None:
    active_values = get_active_document_type_values("china_sea")

    assert "CMR" not in active_values
    assert "FORM_A" not in active_values
    assert "EAV" not in active_values
    assert "CT-3" not in active_values
    assert "T1" not in active_values


def test_confirm_prep_request_rejects_unknown_profile() -> None:
    ConfirmPrepRequest(document_profile="china_sea")

    with pytest.raises(ValidationError):
        ConfirmPrepRequest(document_profile="unknown")
