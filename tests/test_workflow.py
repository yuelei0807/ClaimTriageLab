"""Task 06 durable pause, authorization, resume, and reviewer UI tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claimtriagelab.tools.registry import UnauthorizedToolError
from claimtriagelab.workflow.app import ReviewerSecurity, create_app, csrf_token
from claimtriagelab.workflow.service import WorkflowService


def seed_case(service: WorkflowService) -> None:
    claim = {
        "claim_id": "claim_workflow_001",
        "policy_id": "policy_workflow_001",
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
            "evidence_id": f"ev_workflow_{index}",
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
        {"policy_id": "policy_workflow_001", "status": "active"},
        evidence,
    )


def test_pending_case_survives_restart_and_authorized_resume(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as first:
        seed_case(first)
        pending = first.start("claim_workflow_001")
        assert pending["stage"] == "pending_review"
        assert pending["paused"] is True
        assert pending["thread_id"] == "claim:claim_workflow_001"

    with WorkflowService(database) as restarted:
        restored = restarted.status("claim_workflow_001")
        assert restored["stage"] == "pending_review"
        with pytest.raises(UnauthorizedToolError):
            restarted.resume(
                "claim_workflow_001",
                actor_id="reader_001",
                roles=frozenset({"claim_reader"}),
                decision="approve_referral",
                reason="Escalate for authorized review",
                idempotency_key="workflow-review-unauthorized",
                correlation_id="corr_unauthorized",
            )
        completed = restarted.resume(
            "claim_workflow_001",
            actor_id="reviewer_001",
            roles=frozenset({"reviewer"}),
            decision="approve_referral",
            reason="Escalate for authorized review",
            idempotency_key="workflow-review-authorized",
            correlation_id="corr_authorized",
        )
        assert completed["stage"] == "complete"
        assert completed["paused"] is False
        assert completed["review"]["reviewer_id"] == "reviewer_001"
        events = restarted.store.audit_events()
        assert len(events) == 1
        assert events[0]["tool_name"] == "save_review"
        assert events[0]["status"] == "success"


def test_start_is_idempotent_while_case_is_pending(tmp_path: Path) -> None:
    with WorkflowService(tmp_path / "workflow.sqlite3") as service:
        seed_case(service)
        first = service.start("claim_workflow_001")
        second = service.start("claim_workflow_001")
        assert first["stage"] == second["stage"] == "pending_review"
        assert first["brief"] == second["brief"]


def test_browser_auth_redirect_returns_to_requested_page(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    security = ReviewerSecurity("ui_reviewer", "strong-test-password", "csrf-test-secret")
    app = create_app(database, security)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/cases/claim_workflow_001?view=activity", headers={"accept": "text/html"}
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?return_to=")


def test_local_reviewer_page_can_submit_a_decision(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as service:
        seed_case(service)
        service.start("claim_workflow_001")
    security = ReviewerSecurity("ui_reviewer", "strong-test-password", "csrf-test-secret")
    app = create_app(database, security)
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={
                "username": security.username,
                "password": security.password,
                "csrf": csrf_token(security, "login"),
            },
        )
        assert login.status_code == 200
        assert "Claim review queue" in login.text
        page = client.get("/cases/claim_workflow_001")
        assert page.status_code == 200
        assert "Pending Review" in page.text
        assert "Why this case was prioritized" in page.text
        assert "Source evidence" in page.text
        assert 'type="hidden" name="idempotency_key"' in page.text
        assert "Idempotency key" not in page.text
        response = client.post(
            "/cases/claim_workflow_001/review",
            data={
                "decision": "request_information",
                "reason": "Please obtain the repair estimate",
                "idempotency_key": "workflow-review-from-ui",
                "csrf": csrf_token(security, "claim_workflow_001"),
            },
        )
        assert response.status_code == 200
        assert "complete" in response.text
    with WorkflowService(database) as restarted:
        state = restarted.status("claim_workflow_001")
        assert state["review"]["reviewer_id"] == "ui_reviewer"


def test_reviewer_page_enforces_auth_csrf_and_body_limit(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as service:
        seed_case(service)
        service.start("claim_workflow_001")
    security = ReviewerSecurity("reviewer", "test-password", "csrf-secret", max_request_bytes=512)
    app = create_app(database, security)
    with TestClient(app) as client:
        assert client.get("/cases/claim_workflow_001").status_code == 401
        client.post(
            "/login",
            data={
                "username": security.username,
                "password": security.password,
                "csrf": csrf_token(security, "login"),
            },
        )
        invalid_csrf = client.post(
            "/cases/claim_workflow_001/review",
            data={
                "decision": "approve_referral",
                "reason": "Authorized reason",
                "idempotency_key": "security-review-0001",
                "csrf": "invalid",
            },
        )
        assert invalid_csrf.status_code == 403
        oversized = client.post(
            "/cases/claim_workflow_001/review",
            content=b"x" * 513,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert oversized.status_code == 413


def test_authenticated_webhook_continues_langgraph_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as service:
        seed_case(service)
        service.start("claim_workflow_001")
    monkeypatch.setenv("CLAIMTRIAGE_WEBHOOK_API_KEY", "test-webhook-secret")
    app = create_app(database, ReviewerSecurity("reviewer", "password", "csrf-secret"))
    body = {
        "decision": "approve_referral",
        "reason": "The documented high value collision warrants specialist investigation.",
        "idempotency_key": "webhook-review-0001",
        "actor_id": "api_reviewer",
    }
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/cases/claim_workflow_001/reviews", json=body)
        assert unauthorized.status_code == 401
        response = client.post(
            "/api/v1/cases/claim_workflow_001/reviews",
            json=body,
            headers={"x-api-key": "test-webhook-secret"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "claim_workflow_001"
    assert payload["thread_id"] == "claim:claim_workflow_001"
    assert payload["trace_id"].startswith("trace_")
    assert payload["stage"] == "complete"
    followup_body = body | {
        "reason": "A second reviewer confirmed the documented collision requires investigation.",
        "idempotency_key": "webhook-review-0002",
    }
    followup_app = create_app(database, ReviewerSecurity("reviewer", "password", "csrf"))
    with TestClient(followup_app) as client:
        followup = client.post(
            "/api/v1/cases/claim_workflow_001/reviews",
            json=followup_body,
            headers={"x-api-key": "test-webhook-secret"},
        )
    assert followup.status_code == 200
    assert followup.json()["stage"] == "complete"
    assert followup.json()["agent_followup"]["action"] == "prepare_referral_handoff"


def test_completed_case_accepts_append_only_followup_review(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as service:
        seed_case(service)
        service.start("claim_workflow_001")
        service.resume(
            "claim_workflow_001",
            actor_id="first_reviewer",
            roles=frozenset({"reviewer"}),
            decision="approve_referral",
            reason="Initial referral decision",
            idempotency_key="initial-review-0001",
            correlation_id="corr_initial",
        )
    security = ReviewerSecurity("followup_reviewer", "test-password", "csrf-secret")
    app = create_app(database, security)
    with TestClient(app) as client:
        client.post(
            "/login",
            data={
                "username": security.username,
                "password": security.password,
                "csrf": csrf_token(security, "login"),
            },
        )
        page = client.get("/cases/claim_workflow_001")
        assert "Add a follow-up review" in page.text
        response = client.post(
            "/cases/claim_workflow_001/review",
            data={
                "decision": "request_information",
                "reason": "New evidence requires clarification",
                "idempotency_key": "followup-review-0001",
                "csrf": csrf_token(security, "claim_workflow_001"),
            },
        )
        assert response.status_code == 200
        assert "New evidence requires clarification" in response.text
    with WorkflowService(database) as service:
        reviews = service.store.reviews_for_case("claim_workflow_001")
        assert [review["reviewer_id"] for review in reviews] == [
            "first_reviewer",
            "followup_reviewer",
        ]
        assert service.store.verify_audit_integrity() is True


def test_dashboard_can_reset_showcase_without_server_restart(tmp_path: Path) -> None:
    database = tmp_path / "showcase.sqlite3"
    security = ReviewerSecurity("showcase_reviewer", "test-password", "csrf-secret")
    app = create_app(database, security)
    with TestClient(app) as client:
        client.post(
            "/login",
            data={
                "username": security.username,
                "password": security.password,
                "csrf": csrf_token(security, "login"),
            },
        )
        response = client.post(
            "/showcase/reset",
            data={"csrf": csrf_token(security, "showcase-reset")},
        )
        assert response.status_code == 200
        assert "Total cases</span><strong>4" in response.text
        assert "Pending review</span><strong>3" in response.text


def test_request_information_continues_agent_and_persists_trajectory(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as service:
        seed_case(service)
        service.start("claim_workflow_001")
        completed = service.resume(
            "claim_workflow_001",
            actor_id="reviewer_001",
            roles=frozenset({"reviewer"}),
            decision="request_information",
            reason="Obtain the repair estimate and police report",
            idempotency_key="request-information-001",
            correlation_id="corr_request_information",
        )
        assert completed["agent_followup"]["action"] == "collect_information"
        assert "repair_estimate" in completed["agent_followup"]["missing_information"]
        traces = service.trajectories.traces_for_thread("claim:claim_workflow_001")
        assert [trace["task_type"] for trace in traces] == [
            "initial_triage",
            "review_continuation",
        ]
        continuation = traces[-1]
        continuation_trace_id = continuation["trace_id"]
        assert [
            run["step_name"]
            for run in service.trajectories.runs_for_trace(continuation["trace_id"])
        ] == ["human_review", "post_review_action"]
        assert all(
            evaluation["severity"] == "pass"
            for evaluation in service.trajectories.evaluations_for_trace(continuation["trace_id"])
        )
    with WorkflowService(database) as restarted:
        assert len(restarted.trajectories.traces_for_thread("claim:claim_workflow_001")) == 2
        assert restarted.trajectories.get_trace(continuation_trace_id) is not None
    security = ReviewerSecurity("reviewer", "test-password", "csrf-secret")
    app = create_app(database, security)
    with TestClient(app) as client:
        client.post(
            "/login",
            data={
                "username": security.username,
                "password": security.password,
                "csrf": csrf_token(security, "login"),
            },
        )
        graph = client.get(f"/cases/claim_workflow_001/graph?trace_id={continuation_trace_id}")
        assert graph.status_code == 200
        assert continuation_trace_id in graph.text
        assert "repair_estimate" in graph.text


def test_activity_ui_has_run_trace_and_thread_views(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    with WorkflowService(database) as service:
        seed_case(service)
        service.start("claim_workflow_001")
    security = ReviewerSecurity("reviewer", "test-password", "csrf-secret")
    app = create_app(database, security)
    with TestClient(app) as client:
        client.post(
            "/login",
            data={
                "username": security.username,
                "password": security.password,
                "csrf": csrf_token(security, "login"),
            },
        )
        for tab, expected in (
            ("run", "Prior context"),
            ("trace", "Required execution steps are present and ordered."),
            ("thread", "Thread identity"),
        ):
            response = client.get(f"/cases/claim_workflow_001/activity?tab={tab}")
            assert response.status_code == 200
            assert expected in response.text
        graph = client.get("/cases/claim_workflow_001/graph")
        assert graph.status_code == 200
        assert "Agent execution graph" in graph.text
        assert "Human Review Checkpoint" in graph.text
        assert "Whole thread flow" in graph.text
        assert '<details class="graph-node' in graph.text
        assert "Prior context" in graph.text
        assert 'aria-label="Primary navigation"' in graph.text
        assert ">Dashboard</a>" in graph.text
        assert ">Case</a>" in graph.text
        assert ">Activity</a>" in graph.text
        assert ">Node graph</a>" in graph.text


def test_trajectory_evaluator_flags_context_drift(tmp_path: Path) -> None:
    with WorkflowService(tmp_path / "workflow.sqlite3") as service:
        seed_case(service)
        service.start("claim_workflow_001")
        trace = service.trajectories.start_trace(
            "claim:claim_workflow_001",
            "claim_workflow_001",
            "review_continuation",
            "Synthetic negative evaluation fixture",
        )
        service.trajectories.record_run(
            trace,
            "human_review",
            prior_context={"case_id": "another_case"},
        )
        service.trajectories.finish_trace(trace, "complete", {})
        findings = service.trajectories.evaluations_for_trace(trace)
        failures = {item["evaluator_name"] for item in findings if item["severity"] == "fail"}
        assert failures == {"required_step_sequence", "context_consistency"}
