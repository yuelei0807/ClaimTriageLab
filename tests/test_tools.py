"""Task 05 allowlist, authorization, audit, retry, and idempotency tests."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from claimtriagelab.tools.contracts import ToolContext
from claimtriagelab.tools.registry import (
    InvalidToolInputError,
    ToolDefinition,
    ToolRegistry,
    ToolTimeoutError,
    UnauthorizedToolError,
    UnknownToolError,
)
from claimtriagelab.tools.store import ToolStore


def build_registry(tmp_path: Path) -> tuple[ToolRegistry, ToolStore]:
    store = ToolStore(tmp_path / "tools.sqlite3")
    claim = {
        "claim_id": "claim_001",
        "policy_id": "policy_001",
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
            "evidence_id": f"ev_{index:03d}",
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
    store.seed_case(claim, {"policy_id": "policy_001", "status": "active"}, evidence)
    return ToolRegistry(store), store


def reader() -> ToolContext:
    return ToolContext("reader_001", frozenset({"claim_reader"}), "corr_read")


def reviewer() -> ToolContext:
    return ToolContext("reviewer_001", frozenset({"reviewer"}), "corr_review")


def test_registry_has_only_explicit_tools_and_reads_records(tmp_path: Path) -> None:
    registry, store = build_registry(tmp_path)
    assert registry.allowed_tools == (
        "calculate_indicators",
        "get_claim",
        "get_evidence",
        "get_policy",
        "save_review",
    )
    claim = registry.execute("get_claim", {"claim_id": "claim_001"}, reader())
    result = registry.execute("calculate_indicators", {"claim_id": "claim_001"}, reader())
    assert claim["policy_id"] == "policy_001"
    assert result["category"] == "priority_review"
    assert result["model_version"] == "rules-v1"
    assert result["evidence_ids"]
    assert [event["status"] for event in store.audit_events()] == ["success", "success"]


def test_unauthorized_save_is_rejected_and_audited(tmp_path: Path) -> None:
    registry, store = build_registry(tmp_path)
    payload = {
        "case_id": "claim_001",
        "decision": "approve_referral",
        "reason": "Synthetic test reason",
        "idempotency_key": "review-key-0001",
    }
    with pytest.raises(UnauthorizedToolError):
        registry.execute("save_review", payload, reader())
    event = store.audit_events()[0]
    assert event["status"] == "denied"
    assert event["error_code"] == "unauthorized"
    arguments = json.loads(event["arguments_json"])
    assert "reason" not in arguments
    assert "idempotency_key" not in arguments
    assert arguments["idempotency_key_hash"]


def test_malformed_and_unknown_calls_are_rejected_and_audited(tmp_path: Path) -> None:
    registry, store = build_registry(tmp_path)
    with pytest.raises(InvalidToolInputError):
        registry.execute("get_claim", {"claim_id": "invalid id", "extra": True}, reader())
    with pytest.raises(UnknownToolError):
        registry.execute("delete_claim", {"claim_id": "claim_001"}, reviewer())
    events = store.audit_events()
    assert [(event["tool_name"], event["error_code"]) for event in events] == [
        ("get_claim", "invalid_input"),
        ("delete_claim", "unknown_tool"),
    ]


def test_save_review_is_idempotent(tmp_path: Path) -> None:
    registry, store = build_registry(tmp_path)
    payload = {
        "case_id": "claim_001",
        "decision": "request_information",
        "reason": "Obtain the missing repair estimate",
        "idempotency_key": "review-key-0002",
    }
    first = registry.execute("save_review", payload, reviewer())
    second = registry.execute("save_review", payload, reviewer())
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert first["review"]["review_id"] == second["review"]["review_id"]
    with store.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
    assert count == 1
    assert [event["status"] for event in store.audit_events()] == ["success", "success"]


def test_idempotency_key_cannot_be_reused_for_different_decision(tmp_path: Path) -> None:
    registry, store = build_registry(tmp_path)
    payload = {
        "case_id": "claim_001",
        "decision": "request_information",
        "reason": "Obtain the missing repair estimate",
        "idempotency_key": "review-key-0003",
    }
    registry.execute("save_review", payload, reviewer())
    with pytest.raises(InvalidToolInputError, match="another review payload"):
        registry.execute("save_review", payload | {"decision": "reject_referral"}, reviewer())
    assert [event["status"] for event in store.audit_events()] == ["success", "rejected"]


def test_transient_lock_is_retried_and_attempt_count_is_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = build_registry(tmp_path)
    definition = registry._definitions["get_claim"]
    calls = 0

    def flaky_handler(request, context, started, deadline, attempt_count):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise sqlite3.OperationalError("database is locked")
        return definition.handler(request, context, started, deadline, attempt_count)

    monkeypatch.setitem(
        registry._definitions,
        "get_claim",
        ToolDefinition(definition.input_model, definition.required_roles, flaky_handler),
    )
    result = registry.execute("get_claim", {"claim_id": "claim_001"}, reader())
    assert result["claim_id"] == "claim_001"
    assert store.audit_events()[0]["attempt_count"] == 3


def test_execution_budget_is_enforced_and_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = build_registry(tmp_path)
    definition = registry._definitions["get_claim"]

    def slow_handler(request, context, started, deadline, attempt_count):
        time.sleep(0.02)
        return definition.handler(request, context, started, deadline, attempt_count)

    monkeypatch.setitem(
        registry._definitions,
        "get_claim",
        ToolDefinition(definition.input_model, definition.required_roles, slow_handler),
    )
    short_budget = ToolContext(
        "reader_001", frozenset({"claim_reader"}), "corr_timeout", timeout_ms=10
    )
    with pytest.raises(ToolTimeoutError):
        registry.execute("get_claim", {"claim_id": "claim_001"}, short_budget)
    event = store.audit_events()[0]
    assert event["status"] == "rejected"
    assert event["error_code"] == "timeout"


def test_timed_out_review_is_not_committed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, store = build_registry(tmp_path)
    definition = registry._definitions["save_review"]

    def slow_handler(request, context, started, deadline, attempt_count):
        time.sleep(0.02)
        return definition.handler(request, context, started, deadline, attempt_count)

    monkeypatch.setitem(
        registry._definitions,
        "save_review",
        ToolDefinition(definition.input_model, definition.required_roles, slow_handler),
    )
    context = ToolContext(
        "reviewer_001", frozenset({"reviewer"}), "corr_write_timeout", timeout_ms=10
    )
    payload = {
        "case_id": "claim_001",
        "decision": "request_information",
        "reason": "Obtain the missing repair estimate",
        "idempotency_key": "review-key-timeout",
    }
    with pytest.raises(ToolTimeoutError):
        registry.execute("save_review", payload, context)
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0
    assert store.audit_events()[0]["error_code"] == "timeout"


def test_review_and_success_audit_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store = build_registry(tmp_path)

    def fail_audit(*args, **kwargs):
        raise sqlite3.OperationalError("simulated audit failure")

    monkeypatch.setattr(store, "_insert_audit", fail_audit)
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError, match="simulated audit failure"):
        store.save_review_with_audit(
            case_id="claim_001",
            reviewer_id="reviewer_001",
            decision="request_information",
            reason="Obtain the missing repair estimate",
            idempotency_key="review-key-atomic",
            correlation_id="corr_atomic",
            arguments={"case_id": "claim_001"},
            deadline_monotonic=started + 1,
            started_monotonic=started,
            attempt_count=1,
        )
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0


def test_audit_events_are_database_immutable(tmp_path: Path) -> None:
    registry, store = build_registry(tmp_path)
    registry.execute("get_claim", {"claim_id": "claim_001"}, reader())
    with store.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE audit_events SET status = 'changed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM audit_events")
