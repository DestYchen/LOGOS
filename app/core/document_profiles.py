from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.core.enums import DocumentType

DEFAULT_DOCUMENT_PROFILE = "standard"

DOCUMENT_PROFILE_OPTIONS: List[Dict[str, str]] = [
    {"key": DEFAULT_DOCUMENT_PROFILE, "label": "Стандартно"},
    {"key": "china_sea", "label": "Китайские документы"},
]

_STANDARD_EXPECTED_DOC_TYPES: List[Dict[str, Optional[str]]] = [
    {"display_key": "CONTRACT", "label": "Контракт", "actual_type": "CONTRACT"},
    {"display_key": "ADDENDUM", "label": "Доп. соглашение", "actual_type": None},
    {"display_key": "PROFORMA", "label": "Проформа", "actual_type": "PROFORMA"},
    {"display_key": "INVOICE", "label": "Инвойс", "actual_type": "INVOICE"},
    {"display_key": "BILL_OF_LADING", "label": "Коносамент", "actual_type": "BILL_OF_LANDING"},
    {"display_key": "CMR", "label": "CMR", "actual_type": "CMR"},
    {"display_key": "PACKING_LIST", "label": "Пак-лист", "actual_type": "PACKING_LIST"},
    {"display_key": "PRICE_LIST_1", "label": "Прайс-лист 1", "actual_type": "PRICE_LIST_1"},
    {"display_key": "PRICE_LIST_2", "label": "Прайс-лист 2", "actual_type": "PRICE_LIST_2"},
    {"display_key": "QUALITY_CERTIFICATE", "label": "Сертификат качества", "actual_type": "QUALITY_CERTIFICATE"},
    {"display_key": "VETERINARY_CERTIFICATE", "label": "Вет. сертификат", "actual_type": "VETERINARY_CERTIFICATE"},
    {"display_key": "EXPORT_DECLARATION", "label": "Экспортная декларация", "actual_type": "EXPORT_DECLARATION"},
    {"display_key": "SPECIFICATION", "label": "Спецификация", "actual_type": "SPECIFICATION"},
    {"display_key": "CERTIFICATE_OF_ORIGIN", "label": "Сертификат происхождения", "actual_type": "CERTIFICATE_OF_ORIGIN"},
    {"display_key": "FORM_A", "label": "FORM A", "actual_type": "FORM_A"},
    {"display_key": "EAV", "label": "EAV", "actual_type": "EAV"},
    {"display_key": "CT-3", "label": "CT-3", "actual_type": "CT-3"},
    {"display_key": "T1", "label": "T1", "actual_type": "T1"},
]

_CHINA_SEA_EXPECTED_DOC_TYPES: List[Dict[str, Optional[str]]] = [
    {"display_key": "CONTRACT", "label": "Контракт", "actual_type": "CONTRACT"},
    {"display_key": "ADDENDUM", "label": "Доп. соглашение", "actual_type": None},
    {"display_key": "PROFORMA", "label": "Проформа", "actual_type": "PROFORMA"},
    {"display_key": "BILL_OF_LADING", "label": "Коносамент", "actual_type": "BILL_OF_LANDING"},
    {"display_key": "PACKING_LIST", "label": "Пак-лист", "actual_type": "PACKING_LIST"},
    {"display_key": "INVOICE", "label": "Инвойс", "actual_type": "INVOICE"},
    {"display_key": "PRICE_LIST_1", "label": "Прайс-лист 1", "actual_type": "PRICE_LIST_1"},
    {"display_key": "PRICE_LIST_2", "label": "Прайс-лист 2", "actual_type": "PRICE_LIST_2"},
    {"display_key": "VETERINARY_CERTIFICATE", "label": "Вет. сертификат", "actual_type": "VETERINARY_CERTIFICATE"},
    {"display_key": "QUALITY_CERTIFICATE", "label": "Сертификат качества", "actual_type": "QUALITY_CERTIFICATE"},
    {"display_key": "CERTIFICATE_OF_ORIGIN", "label": "Сертификат происхождения", "actual_type": "CERTIFICATE_OF_ORIGIN"},
    {"display_key": "EXPORT_DECLARATION", "label": "Экспортная декларация", "actual_type": "EXPORT_DECLARATION"},
    {"display_key": "SPECIFICATION", "label": "Спецификация", "actual_type": "SPECIFICATION"},
]

_PROFILE_EXPECTED_DOC_TYPES: Dict[str, List[Dict[str, Optional[str]]]] = {
    DEFAULT_DOCUMENT_PROFILE: _STANDARD_EXPECTED_DOC_TYPES,
    "china_sea": _CHINA_SEA_EXPECTED_DOC_TYPES,
}


def is_valid_document_profile(profile: str | None) -> bool:
    return profile in _PROFILE_EXPECTED_DOC_TYPES


def normalize_document_profile(profile: str | None) -> str:
    if is_valid_document_profile(profile):
        return str(profile)
    return DEFAULT_DOCUMENT_PROFILE


def get_document_profile(meta: Mapping[str, Any] | None) -> str:
    if not isinstance(meta, Mapping):
        return DEFAULT_DOCUMENT_PROFILE
    raw_value = meta.get("document_profile")
    if not isinstance(raw_value, str):
        return DEFAULT_DOCUMENT_PROFILE
    return normalize_document_profile(raw_value)


def get_document_profile_options() -> List[Dict[str, str]]:
    return [dict(entry) for entry in DOCUMENT_PROFILE_OPTIONS]


def get_expected_doc_types(profile: str | None) -> List[Dict[str, Optional[str]]]:
    resolved_profile = normalize_document_profile(profile)
    return [dict(entry) for entry in _PROFILE_EXPECTED_DOC_TYPES[resolved_profile]]


def get_field_matrix_doc_type_map(profile: str | None) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for entry in get_expected_doc_types(profile):
        display_key = entry.get("display_key")
        actual_type = entry.get("actual_type")
        if isinstance(display_key, str) and isinstance(actual_type, str):
            mapping[display_key] = actual_type
    return mapping


def get_field_matrix_doc_types(profile: str | None) -> List[str]:
    return list(get_field_matrix_doc_type_map(profile).keys())


def get_active_document_types(profile: str | None) -> set[DocumentType]:
    result: set[DocumentType] = set()
    for actual_type in get_field_matrix_doc_type_map(profile).values():
        if actual_type == "CT-3":
            result.add(DocumentType.CT_3)
            continue
        enum_value = DocumentType.__members__.get(actual_type)
        if enum_value is not None:
            result.add(enum_value)
            continue
        for doc_type in DocumentType:
            if doc_type.value == actual_type:
                result.add(doc_type)
                break
    return result


def get_active_document_type_values(profile: str | None) -> set[str]:
    return {doc_type.value for doc_type in get_active_document_types(profile)}
