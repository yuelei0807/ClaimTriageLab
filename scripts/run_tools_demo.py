"""Create machine-readable successful and denied Task 05 audit examples."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from claimtriagelab.tools.contracts import ToolContext
from claimtriagelab.tools.registry import ToolRegistry, UnauthorizedToolError
from claimtriagelab.tools.store import ToolStore

DATABASE = Path("artifacts/tools-demo.sqlite3")
OUTPUT = Path("artifacts/tools-demo-audit.json")


def main() -> None:
    if DATABASE.exists():
        DATABASE.unlink()
    store = ToolStore(DATABASE)
    claim = {
        "claim_id": "claim_demo_001",
        "policy_id": "policy_demo_001",
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
        {"evidence_id": f"ev_demo_{index}", "field_name": field, "value": value}
        for index, (field, value) in enumerate(
            ((key, value) for key, value in claim.items() if key not in {"claim_id", "policy_id"}),
            start=1,
        )
    ]
    store.seed_case(claim, {"policy_id": "policy_demo_001", "status": "active"}, evidence)
    registry = ToolRegistry(store)
    reader = ToolContext("reader_demo", frozenset({"claim_reader"}), "demo_success")
    result = registry.execute("calculate_indicators", {"claim_id": "claim_demo_001"}, reader)
    with suppress(UnauthorizedToolError):
        registry.execute(
            "save_review",
            {
                "case_id": "claim_demo_001",
                "decision": "approve_referral",
                "reason": "Expected denial in demo",
                "idempotency_key": "demo-denied-key-001",
            },
            reader,
        )
    report = {
        "allowed_tools": registry.allowed_tools,
        "successful_result": result,
        "audit_events": store.audit_events(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
