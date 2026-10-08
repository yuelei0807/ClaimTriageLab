"""Reusable synthetic showcase data for local and hosted demos."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

from claimtriagelab.workflow.service import WorkflowService

CASES = (
    (
        "claim_showcase_priority",
        "High-value collision",
        45_000,
        50_000,
        3,
        "2026-01-10",
        "2026-01-01",
        "Major",
        "No",
    ),
    (
        "claim_showcase_routine",
        "Minor windshield damage",
        1_200,
        40_000,
        0,
        "2026-02-04",
        "2026-02-03",
        "Minor",
        "Yes",
    ),
    (
        "claim_showcase_incomplete",
        "Missing incident report",
        18_000,
        50_000,
        1,
        "2026-03-08",
        "2026-03-07",
        "Moderate",
        "",
    ),
    (
        "claim_showcase_complete",
        "Completed theft referral",
        38_000,
        42_000,
        2,
        "2026-04-09",
        "2026-04-01",
        "Major",
        "Yes",
    ),
)


def prepare_showcase_database(database_path: Path) -> None:
    """Replace a closed demo database with the canonical four-case showcase."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(f"{database_path}{suffix}").unlink(missing_ok=True)
    with WorkflowService(database_path) as service:
        for index, values in enumerate(CASES, start=1):
            (
                claim_id,
                display_name,
                amount,
                coverage,
                previous,
                claim_date,
                incident_date,
                severity,
                police_report,
            ) = values
            claim = {
                "claim_id": claim_id,
                "display_name": display_name,
                "policy_id": f"policy_showcase_{index:03d}",
                "claim_amount": amount,
                "coverage_amount": coverage,
                "previous_claims": previous,
                "claim_date": claim_date,
                "incident_date": incident_date,
                "accident_severity": severity,
                "police_report": police_report,
                "policy_active": "Yes",
            }
            evidence = [
                {
                    "evidence_id": f"ev_showcase_{index}_{item_index}",
                    "field_name": field,
                    "value": value,
                }
                for item_index, (field, value) in enumerate(
                    (
                        (field, value)
                        for field, value in claim.items()
                        if field not in {"claim_id", "policy_id", "display_name"}
                    ),
                    start=1,
                )
            ]
            service.store.seed_case(
                claim,
                {"policy_id": claim["policy_id"], "status": "active"},
                evidence,
            )
            service.start(claim_id)
        service.resume(
            "claim_showcase_complete",
            actor_id="showcase_reviewer",
            roles=frozenset({"reviewer"}),
            decision="approve_referral",
            reason="Escalated after confirming the theft report and coverage details.",
            idempotency_key="showcase-completed-review-001",
            correlation_id="showcase_seed",
        )
