"""Deterministic intake-time indicators and routing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from claimtriagelab.domain.contracts import Indicator, TriageResult

RULE_VERSION = "rules-v1"
THRESHOLD_VERSION = "review-capacity-10pct-v1"
RULE_THRESHOLD = 0.3
REQUIRED_FIELDS = {
    "claim_amount",
    "coverage_amount",
    "previous_claims",
    "claim_date",
    "incident_date",
    "accident_severity",
    "police_report",
    "policy_active",
}


def _as_date(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def calculate_rule_signals(claim: dict[str, Any]) -> list[tuple[str, float, str, tuple[str, ...]]]:
    """Calculate explainable signals from fields plausibly available at intake."""
    delay = (_as_date(claim["claim_date"]) - _as_date(claim["incident_date"])).days
    amount = float(claim["claim_amount"])
    coverage = float(claim["coverage_amount"])
    signals: list[tuple[str, float, str, tuple[str, ...]]] = []
    if amount >= 35_000:
        signals.append(
            ("high_claim_amount", 0.2, "claim_amount is at least 35000", ("claim_amount",))
        )
    if int(claim["previous_claims"]) >= 3:
        signals.append(
            (
                "multiple_previous_claims",
                0.2,
                "previous_claims is at least 3",
                ("previous_claims",),
            )
        )
    if delay > 5:
        signals.append(
            (
                "reporting_delay",
                0.2,
                "claim was reported more than 5 days later",
                ("claim_date", "incident_date"),
            )
        )
    if claim["accident_severity"] in {"Major", "Total Loss"} and claim["police_report"] == "No":
        signals.append(
            (
                "severe_without_report",
                0.2,
                "severe incident has no police report",
                ("accident_severity", "police_report"),
            )
        )
    if coverage > 0 and amount / coverage >= 0.8:
        signals.append(
            (
                "high_coverage_ratio",
                0.1,
                "claim amount is at least 80% of coverage",
                ("claim_amount", "coverage_amount"),
            )
        )
    if claim["policy_active"] != "Yes":
        signals.append(
            (
                "inactive_policy",
                0.1,
                "policy was not active at incident time",
                ("policy_active",),
            )
        )
    return signals


def rule_score(claim: dict[str, Any]) -> float:
    """Return a bounded transparent score, with missing inputs handled by the caller."""
    return round(min(1.0, sum(weight for _, weight, _, _ in calculate_rule_signals(claim))), 6)


def triage_with_rules(
    claim: dict[str, Any], evidence_by_field: dict[str, str], threshold: float = RULE_THRESHOLD
) -> TriageResult:
    """Create a validated result; missing or contradictory inputs require human review."""
    missing = sorted(field for field in REQUIRED_FIELDS if claim.get(field) in {None, ""})
    contradictions = []
    if not missing:
        try:
            if _as_date(claim["claim_date"]) < _as_date(claim["incident_date"]):
                contradictions.append("claim_date precedes incident_date")
            if float(claim["claim_amount"]) > float(claim["coverage_amount"]):
                contradictions.append("claim_amount exceeds coverage_amount")
            int(claim["previous_claims"])
        except (TypeError, ValueError, OverflowError):
            contradictions.append("one or more claim fields have an invalid format")
    cited_fields = sorted(REQUIRED_FIELDS - set(missing))
    evidence_ids = sorted(
        {evidence_by_field[field] for field in cited_fields if field in evidence_by_field}
    )
    uncited = sorted(field for field in cited_fields if field not in evidence_by_field)
    missing.extend(f"evidence:{field}" for field in uncited)
    if missing or contradictions:
        return TriageResult(
            category="insufficient_information",
            threshold_version=THRESHOLD_VERSION,
            indicators=[],
            missing_data=missing,
            contradictory_data=contradictions,
            evidence_ids=evidence_ids,
            model_version=RULE_VERSION,
            generated_at=datetime.now(UTC),
        )

    try:
        signals = calculate_rule_signals(claim)
    except (TypeError, ValueError, OverflowError):
        return TriageResult(
            category="insufficient_information",
            threshold_version=THRESHOLD_VERSION,
            indicators=[],
            missing_data=[],
            contradictory_data=["one or more claim fields have an invalid format"],
            evidence_ids=evidence_ids,
            model_version=RULE_VERSION,
            generated_at=datetime.now(UTC),
        )
    indicators = [
        Indicator(
            indicator_id=name,
            value=True,
            derivation=derivation,
            evidence_ids=sorted({evidence_by_field[field] for field in fields}),
            rule_version=RULE_VERSION,
            quality_flag="verified",
        )
        for name, _, derivation, fields in signals
    ]
    score = rule_score(claim)
    return TriageResult(
        category="priority_review" if score >= threshold else "routine_review",
        score=score,
        threshold_version=THRESHOLD_VERSION,
        indicators=indicators,
        missing_data=[],
        contradictory_data=[],
        evidence_ids=evidence_ids,
        model_version=RULE_VERSION,
        generated_at=datetime.now(UTC),
    )
