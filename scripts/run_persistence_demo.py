"""Demonstrate bounded context and replay from a verified SQLite backup."""

from __future__ import annotations

import json
from pathlib import Path

from claimtriagelab.limits import DEFAULT_LIMITS
from claimtriagelab.persistence import backup_database, restore_database
from claimtriagelab.workflow.service import WorkflowService

ARTIFACT_DIR = Path("artifacts/persistence-demo")
ORIGINAL = ARTIFACT_DIR / "original.sqlite3"
BACKUP = ARTIFACT_DIR / "pending-backup.sqlite3"
RESTORED = ARTIFACT_DIR / "restored.sqlite3"
REPORT = ARTIFACT_DIR / "report.json"
CASE_ID = "claim_context_demo"


def seed(service: WorkflowService) -> None:
    narrative = [
        f"Timeline update {index}. Synthetic supporting detail retained in source storage."
        for index in range(80)
    ]
    claim = {
        "claim_id": CASE_ID,
        "policy_id": "policy_context_demo",
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
        {"evidence_id": f"ev_context_{index}", "field_name": field, "value": value}
        for index, (field, value) in enumerate(
            (
                (field, value)
                for field, value in claim.items()
                if field not in {"claim_id", "policy_id", "narrative_history"}
            ),
            start=1,
        )
    ]
    service.store.seed_case(
        claim, {"policy_id": "policy_context_demo", "status": "active"}, evidence
    )


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (ORIGINAL, BACKUP, RESTORED):
        path.unlink(missing_ok=True)
    with WorkflowService(ORIGINAL) as service:
        seed(service)
        pending = service.start(CASE_ID)
        checkpoint_count = len(service.checkpoint_history(CASE_ID))
    backup_database(ORIGINAL, BACKUP)
    restore_database(BACKUP, RESTORED)
    with WorkflowService(RESTORED) as replay:
        restored = replay.status(CASE_ID)
        completed = replay.resume(
            CASE_ID,
            actor_id="reviewer_restore_demo",
            roles=frozenset({"reviewer"}),
            decision="request_information",
            reason="Confirm the latest supporting document",
            idempotency_key="persistence-demo-review-0001",
            correlation_id="persistence_demo_resume",
        )
        stored_claim = replay.store.get_record("claims", "claim_id", CASE_ID)
        report = {
            "limits": DEFAULT_LIMITS.to_dict(),
            "checkpoint_count_before_backup": checkpoint_count,
            "pending_stage": pending["stage"],
            "restored_stage": restored["stage"],
            "completed_stage": completed["stage"],
            "context": pending["narrative_context"],
            "original_narrative_items_retained": len(stored_claim["narrative_history"]),
            "audit_events": replay.store.audit_events(),
        }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
