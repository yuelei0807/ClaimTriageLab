"""Task 07 context-limit and backup/restore tests."""

from pathlib import Path

import pytest

from claimtriagelab.context import compact_narrative, estimate_tokens
from claimtriagelab.limits import DEFAULT_LIMITS, ResourceLimits
from claimtriagelab.persistence import backup_database, restore_database, verify_database
from claimtriagelab.workflow.service import WorkflowService


def seed_long_case(service: WorkflowService, narrative_items: int = 60) -> list[str]:
    narrative = [
        f"Update {index}: synthetic adjuster note with repeated bounded context "
        f"for the claim timeline and supporting document review. Detail {index}."
        for index in range(narrative_items)
    ]
    claim = {
        "claim_id": "claim_long_001",
        "policy_id": "policy_long_001",
        "claim_amount": 45_000,
        "coverage_amount": 50_000,
        "previous_claims": 3,
        "claim_date": "2026-01-10",
        "incident_date": "2026-01-01",
        "accident_severity": "Major",
        "police_report": "No",
        "policy_active": "Yes",
        "narrative_history": narrative,
    }
    evidence = [
        {"evidence_id": f"ev_long_{index}", "field_name": field, "value": value}
        for index, (field, value) in enumerate(
            (
                (field, value)
                for field, value in claim.items()
                if field not in {"claim_id", "policy_id", "narrative_history"}
            ),
            start=1,
        )
    ]
    service.store.seed_case(claim, {"policy_id": "policy_long_001", "status": "active"}, evidence)
    return narrative


def test_context_compacts_only_when_needed_and_records_provenance() -> None:
    short = ["First update.", "Latest update."]
    unchanged = compact_narrative(short, 100)
    assert unchanged["summary"] is None
    assert unchanged["recent"] == short
    assert unchanged["provenance"]["method"] == "none"

    long = [f"Historical note {index}. Additional detail." for index in range(40)]
    compacted = compact_narrative(long, 100)
    assert compacted["estimated_tokens"] <= 100
    assert compacted["recent"][-1] == long[-1]
    assert compacted["provenance"]["summarized_items"] > 0
    assert (
        len(compacted["provenance"]["source_hashes"]) == compacted["provenance"]["summarized_items"]
    )
    assert compacted["provenance"]["original_estimated_tokens"] == sum(
        estimate_tokens(item) for item in long
    )


def test_long_case_survives_backup_restore_and_replay(tmp_path: Path) -> None:
    original = tmp_path / "original.sqlite3"
    backup = tmp_path / "backups" / "pending.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    with WorkflowService(original) as service:
        narrative = seed_long_case(service)
        pending = service.start("claim_long_001")
        assert pending["stage"] == "pending_review"
        assert pending["narrative_context"]["estimated_tokens"] <= DEFAULT_LIMITS.max_context_tokens
        assert pending["narrative_context"]["provenance"]["summarized_items"] > 0
        assert (
            len(service.checkpoint_history("claim_long_001")) <= DEFAULT_LIMITS.max_workflow_steps
        )

    backup_database(original, backup)
    restore_database(backup, restored)
    verify_database(restored)

    with WorkflowService(restored) as replay:
        restored_state = replay.status("claim_long_001")
        assert restored_state["stage"] == "pending_review"
        stored_claim = replay.store.get_record("claims", "claim_id", "claim_long_001")
        assert stored_claim is not None
        assert stored_claim["narrative_history"] == narrative
        completed = replay.resume(
            "claim_long_001",
            actor_id="reviewer_restore",
            roles=frozenset({"reviewer"}),
            decision="request_information",
            reason="Confirm the most recent repair documentation",
            idempotency_key="restored-review-0001",
            correlation_id="corr_restore",
        )
        assert completed["stage"] == "complete"
        assert replay.store.audit_events()[0]["status"] == "success"


def test_evidence_retrieval_limit_stops_oversized_case(tmp_path: Path) -> None:
    limits = ResourceLimits(max_retrieved_evidence=7)
    with WorkflowService(tmp_path / "limited.sqlite3", limits=limits) as service:
        seed_long_case(service, narrative_items=1)
        with pytest.raises(ValueError, match="evidence retrieval exceeds 7"):
            service.start("claim_long_001")
