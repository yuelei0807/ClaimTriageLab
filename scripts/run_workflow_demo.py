"""Demonstrate durable pause, restart, authorized resume, and audit persistence."""

from __future__ import annotations

import json
from pathlib import Path

from claimtriagelab.workflow.service import WorkflowService

ARTIFACT_DIR = Path("artifacts")
DATABASE = ARTIFACT_DIR / "workflow-demo.sqlite3"
REPORT = ARTIFACT_DIR / "workflow-demo.json"
CASE_ID = "claim_workflow_demo"


def seed(service: WorkflowService) -> None:
    claim = {
        "claim_id": CASE_ID,
        "policy_id": "policy_workflow_demo",
        "claim_amount": 45_000,
        "coverage_amount": 50_000,
        "previous_claims": 3,
        "claim_date": "2026-01-10",
        "incident_date": "2026-01-01",
        "accident_severity": "Major",
        "police_report": "No",
        "policy_active": "Yes",
    }
    evidence = [
        {
            "evidence_id": f"ev_workflow_demo_{index}",
            "field_name": field,
            "value": value,
        }
        for index, (field, value) in enumerate(
            (
                (field, value)
                for field, value in claim.items()
                if field not in {"claim_id", "policy_id"}
            ),
            start=1,
        )
    ]
    service.store.seed_case(
        claim,
        {"policy_id": "policy_workflow_demo", "status": "active"},
        evidence,
    )


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE.unlink(missing_ok=True)
    with WorkflowService(DATABASE) as service:
        seed(service)
        pending = service.start(CASE_ID)
    with WorkflowService(DATABASE) as restarted:
        restored = restarted.status(CASE_ID)
        completed = restarted.resume(
            CASE_ID,
            actor_id="reviewer_demo",
            roles=frozenset({"reviewer"}),
            decision="request_information",
            reason="Obtain the missing repair estimate",
            idempotency_key="workflow-demo-review-0001",
            correlation_id="workflow_demo_resume",
        )
        report = {
            "pending_before_restart": pending,
            "restored_after_restart": restored,
            "completed": completed,
            "audit_events": restarted.store.audit_events(),
        }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
