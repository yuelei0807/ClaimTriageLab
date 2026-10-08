"""Task 01 contract examples and predictable failure paths."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from claimtriagelab.domain.contracts import (
    Claim,
    Evidence,
    Indicator,
    ReviewDecision,
    TriageResult,
    WorkflowState,
)

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def claim_payload() -> dict:
    return {
        "claim_id": "claim_001",
        "policy_id": "policy_001",
        "claimant_id": "person_001",
        "incident_at": "2026-01-01T12:00:00Z",
        "reported_at": "2026-01-02T12:00:00Z",
        "incident_type": "collision",
        "amount": "1200.00",
        "location_region": "NY",
        "narrative": "Synthetic collision report.",
        "document_ids": ["doc_001"],
        "intake_version": "v1",
    }


def test_valid_contract_examples() -> None:
    claim = Claim.model_validate(claim_payload())
    evidence = Evidence(
        evidence_id="ev_001",
        claim_id=claim.claim_id,
        source_type="claim_form",
        source_hash="a" * 64,
        captured_at=NOW,
        extracted_fact="Incident was reported.",
        page_or_field_locator="reported_at",
        extraction_method="form_field",
        quality_flag="verified",
    )
    indicator = Indicator(
        indicator_id="ind_001",
        value=True,
        derivation="Reported after incident",
        evidence_ids=[evidence.evidence_id],
        rule_version="v1",
        quality_flag="verified",
    )
    result = TriageResult(
        category="routine_review",
        score=0.2,
        threshold_version="v1",
        indicators=[indicator],
        missing_data=[],
        contradictory_data=[],
        evidence_ids=[evidence.evidence_id],
        model_version="rules-v1",
        generated_at=NOW,
    )
    decision = ReviewDecision(
        case_id=claim.claim_id,
        reviewer_id="reviewer_001",
        decision="request_information",
        reason="Need another document",
        timestamp=NOW,
    )
    state = WorkflowState(
        case_id=claim.claim_id,
        stage="pending_review",
        evidence_ids=[evidence.evidence_id],
        indicator_ids=[indicator.indicator_id],
        triage_result_id="result_001",
        pending_review_id="review_001",
        errors=[],
        version="v1",
    )
    assert result.evidence_ids == ["ev_001"]
    assert decision.decision == "request_information"
    assert state.stage == "pending_review"


@pytest.mark.parametrize(
    "change",
    [
        {"claim_id": ""},
        {"claim_id": "Jane Smith"},
        {"reported_at": "2025-12-31T12:00:00Z"},
        {"document_ids": ["doc_001", "doc_001"]},
        {"unexpected": "value"},
    ],
)
def test_invalid_claim_fails_predictably(change: dict) -> None:
    with pytest.raises(ValidationError):
        Claim.model_validate(claim_payload() | change)


def test_required_claim_field_fails_predictably() -> None:
    payload = claim_payload()
    del payload["claim_id"]
    with pytest.raises(ValidationError) as error:
        Claim.model_validate(payload)
    assert error.value.errors()[0]["loc"] == ("claim_id",)


def test_uncited_indicator_is_rejected() -> None:
    indicator = Indicator(
        indicator_id="ind_001",
        value=True,
        derivation="Synthetic signal",
        evidence_ids=["ev_001"],
        rule_version="v1",
        quality_flag="uncertain",
    )
    with pytest.raises(ValidationError, match="indicator evidence_ids"):
        TriageResult(
            category="priority_review",
            threshold_version="v1",
            indicators=[indicator],
            missing_data=[],
            contradictory_data=[],
            evidence_ids=[],
            model_version="rules-v1",
            generated_at=NOW,
        )


def test_missing_data_cannot_be_routed_as_priority() -> None:
    with pytest.raises(ValidationError, match="insufficient_information"):
        TriageResult(
            category="priority_review",
            threshold_version="v1",
            indicators=[],
            missing_data=["police_report"],
            contradictory_data=[],
            evidence_ids=[],
            model_version="rules-v1",
            generated_at=NOW,
        )


def test_pending_state_requires_review_id() -> None:
    with pytest.raises(ValidationError, match="pending_review_id"):
        WorkflowState(
            case_id="claim_001",
            stage="pending_review",
            evidence_ids=[],
            indicator_ids=[],
            triage_result_id="result_001",
            pending_review_id=None,
            errors=[],
            version="v1",
        )
