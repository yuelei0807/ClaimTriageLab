"""Transparent baseline routing and evidence-link tests."""

from claimtriagelab.indicators.rules import rule_score, triage_with_rules


def base_claim() -> dict:
    return {
        "claim_amount": 10_000,
        "coverage_amount": 50_000,
        "previous_claims": 0,
        "claim_date": "2026-01-03",
        "incident_date": "2026-01-01",
        "accident_severity": "Minor",
        "police_report": "Yes",
        "policy_active": "Yes",
    }


def evidence() -> dict[str, str]:
    return {field: f"ev_{index}" for index, field in enumerate(base_claim(), start=1)}


def test_routine_rule_result_has_versions_and_evidence() -> None:
    result = triage_with_rules(base_claim(), evidence())
    assert result.category == "routine_review"
    assert result.score == 0
    assert result.model_version == "rules-v1"
    assert result.threshold_version == "review-capacity-10pct-v1"
    assert set(result.evidence_ids) == set(evidence().values())


def test_priority_result_has_transparent_indicators() -> None:
    claim = base_claim() | {
        "claim_amount": 45_000,
        "previous_claims": 4,
        "claim_date": "2026-01-10",
    }
    result = triage_with_rules(claim, evidence())
    assert result.category == "priority_review"
    assert result.score == 0.7
    assert {item.indicator_id for item in result.indicators} == {
        "high_claim_amount",
        "multiple_previous_claims",
        "reporting_delay",
        "high_coverage_ratio",
    }
    assert all(item.evidence_ids for item in result.indicators)
    by_id = {item.indicator_id: item for item in result.indicators}
    assert by_id["high_claim_amount"].evidence_ids == [evidence()["claim_amount"]]
    assert set(by_id["reporting_delay"].evidence_ids) == {
        evidence()["claim_date"],
        evidence()["incident_date"],
    }


def test_missing_or_conflicting_data_routes_to_human_review() -> None:
    missing = triage_with_rules(base_claim() | {"police_report": ""}, evidence())
    conflicting = triage_with_rules(base_claim() | {"claim_date": "2025-12-31"}, evidence())
    incomplete_evidence = evidence()
    incomplete_evidence.pop("policy_active")
    uncited = triage_with_rules(base_claim(), incomplete_evidence)
    assert missing.category == "insufficient_information"
    assert missing.missing_data == ["police_report"]
    assert conflicting.category == "insufficient_information"
    assert conflicting.contradictory_data == ["claim_date precedes incident_date"]
    assert uncited.category == "insufficient_information"
    assert uncited.missing_data == ["evidence:policy_active"]


def test_malformed_values_route_to_human_review() -> None:
    malformed = triage_with_rules(base_claim() | {"claim_amount": "not-a-number"}, evidence())
    assert malformed.category == "insufficient_information"
    assert malformed.contradictory_data == ["one or more claim fields have an invalid format"]


def test_rule_score_is_bounded() -> None:
    claim = base_claim() | {
        "claim_amount": 100_000,
        "coverage_amount": 100_000,
        "previous_claims": 6,
        "claim_date": "2026-01-15",
        "accident_severity": "Total Loss",
        "police_report": "No",
        "policy_active": "No",
    }
    assert rule_score(claim) == 1.0
