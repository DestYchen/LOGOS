from __future__ import annotations

from app.core.document_profiles import get_active_document_type_values
from app.services.validation import (
    ANCHORED_EQUALITY_RULES,
    DATE_RULES,
    GROUP_EQUALITY_RULES,
    _filter_anchored_equality_rule,
    _filter_date_rule,
    _filter_group_equality_rule,
    _filtered_field_comparison_rules,
)


def _find_rule(rules, rule_id: str):
    return next(rule for rule in rules if rule.rule_id == rule_id)


def test_china_profile_drops_date_rule_with_cmr_anchor() -> None:
    active_values = get_active_document_type_values("china_sea")
    rule = _find_rule(DATE_RULES, "date_cmr_after_sources")

    assert _filter_date_rule(rule, active_values) is None


def test_china_profile_keeps_mixed_group_rule_only_for_supported_docs() -> None:
    active_values = get_active_document_type_values("china_sea")
    rule = _find_rule(GROUP_EQUALITY_RULES, "importer_alignment")

    filtered = _filter_group_equality_rule(rule, active_values)

    assert filtered is not None
    assert [ref.doc_type for ref in filtered.refs] == ["BILL_OF_LANDING", "CERTIFICATE_OF_ORIGIN"]


def test_china_profile_keeps_supported_targets_for_exporter_consistency() -> None:
    active_values = get_active_document_type_values("china_sea")
    rule = _find_rule(ANCHORED_EQUALITY_RULES, "exporter_consistency")

    filtered = _filter_anchored_equality_rule(rule, active_values)

    assert filtered is not None
    assert [ref.doc_type for ref in filtered.targets] == ["BILL_OF_LANDING", "CERTIFICATE_OF_ORIGIN"]


def test_china_profile_keeps_supported_targets_for_contract_recipient_rule() -> None:
    active_values = get_active_document_type_values("china_sea")
    rule = _find_rule(ANCHORED_EQUALITY_RULES, "recipient_matches_contract_buyer")

    filtered = _filter_anchored_equality_rule(rule, active_values)

    assert filtered is not None
    assert [ref.doc_type for ref in filtered.targets] == ["BILL_OF_LANDING", "CERTIFICATE_OF_ORIGIN"]


def test_field_comparison_rules_exclude_removed_doc_types_for_china() -> None:
    active_values = get_active_document_type_values("china_sea")
    comparison_rules = _filtered_field_comparison_rules(active_values)

    for rules in comparison_rules.values():
        for rule in rules:
            assert rule.anchor_doc not in {"CMR", "FORM_A", "EAV", "CT-3", "T1"}
            assert {"CMR", "FORM_A", "EAV", "CT-3", "T1"}.isdisjoint(rule.target_docs)
