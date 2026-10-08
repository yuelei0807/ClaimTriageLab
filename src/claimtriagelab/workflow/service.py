"""LangGraph workflow with durable SQLite checkpoints and an authorization boundary."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from claimtriagelab.agent import AgentConfigurationError, ModelDrivenAgent
from claimtriagelab.context import compact_narrative
from claimtriagelab.domain.contracts import TriageCategory
from claimtriagelab.indicators.rules import triage_with_rules
from claimtriagelab.limits import DEFAULT_LIMITS, ResourceLimits
from claimtriagelab.telemetry import TRACER, set_common_attributes
from claimtriagelab.tools.contracts import ToolContext
from claimtriagelab.tools.registry import ToolNotFoundError, ToolRegistry, UnauthorizedToolError
from claimtriagelab.tools.store import ToolStore
from claimtriagelab.trajectory import TrajectoryStore

WORKFLOW_VERSION = "human-review-continuation-v2"
GENERIC_REVIEW_WORDS = {
    "additional",
    "evidence",
    "further",
    "information",
    "investigation",
    "more",
    "need",
    "needed",
    "please",
    "request",
}


class GraphState(TypedDict, total=False):
    case_id: str
    stage: str
    evidence_ids: list[str]
    triage: dict[str, Any]
    brief: dict[str, Any]
    review: dict[str, Any]
    agent_followup: dict[str, Any]
    active_trace_id: str
    narrative_context: dict[str, Any]
    resource_limits: dict[str, int]
    version: str


class WorkflowService:
    """Own a durable workflow graph and enforce reviewer authorization on resume."""

    def __init__(self, database_path: Path, limits: ResourceLimits = DEFAULT_LIMITS) -> None:
        self.limits = limits
        self.store = ToolStore(database_path)
        self.trajectories = TrajectoryStore(database_path)
        self.registry = ToolRegistry(self.store)
        if os.getenv("CLAIMTRIAGE_TEST_MODE") == "1":
            self.agent = None
            self.agent_configuration_error = "deterministic test fixture enabled"
        else:
            try:
                self.agent = ModelDrivenAgent.from_environment(self.registry, self.trajectories)
                self.agent_configuration_error = None
            except AgentConfigurationError as error:
                self.agent = None
                self.agent_configuration_error = str(error)
        self._checkpoint_connection = sqlite3.connect(
            database_path, check_same_thread=False, timeout=0.25
        )
        self._checkpoint_connection.execute("PRAGMA journal_mode = WAL")
        self._checkpoint_connection.execute("PRAGMA busy_timeout = 250")
        self._checkpointer = SqliteSaver(self._checkpoint_connection)
        self._checkpointer.setup()
        self.graph = self._build_graph()

    def close(self) -> None:
        self._checkpoint_connection.close()

    def __enter__(self) -> WorkflowService:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def thread_id(case_id: str) -> str:
        return f"claim:{case_id}"

    @staticmethod
    def _validate_review_reason(decision: str, reason: str) -> None:
        if decision != "request_information":
            return
        words = {word.strip(".,:;!?()[]").lower() for word in reason.split() if word.strip()}
        if not words or not (words - GENERIC_REVIEW_WORDS):
            raise ValueError(
                "Name the specific document, fact, or clarification the agent should investigate."
            )

    def _config(self, case_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": self.thread_id(case_id)},
            "recursion_limit": self.limits.max_workflow_steps,
        }

    def _build_graph(self):
        builder = StateGraph(GraphState)

        def intake(state: GraphState) -> GraphState:
            started = time.monotonic()
            case_id = state["case_id"]
            claim = self.store.get_record("claims", "claim_id", case_id)
            if claim is None:
                raise ToolNotFoundError("case was not found")
            narrative = claim.get("narrative_history", [])
            if not isinstance(narrative, list) or not all(
                isinstance(item, str) for item in narrative
            ):
                raise ValueError("narrative_history must be a list of strings")
            if len(narrative) > self.limits.max_narrative_items:
                raise ValueError(
                    f"narrative history exceeds {self.limits.max_narrative_items} item limit"
                )
            result = {
                "stage": "evidence",
                "narrative_context": compact_narrative(narrative, self.limits.max_context_tokens),
            }
            self.trajectories.record_run(
                state["active_trace_id"],
                "intake",
                started=started,
                prior_context={"case_id": case_id, "stage": state.get("stage")},
                decision={
                    "next_step": "evidence",
                    "reason": "Claim exists and input limits passed.",
                },
                tool_name="get_claim",
                tool_arguments={"claim_id": case_id},
                tool_result={"found": True, "narrative_items": len(narrative)},
            )
            return result

        def evidence(state: GraphState) -> GraphState:
            started = time.monotonic()
            evidence_by_field = self.store.evidence_map(
                state["case_id"], max_results=self.limits.max_retrieved_evidence
            )
            result = {"stage": "triage", "evidence_ids": sorted(evidence_by_field.values())}
            self.trajectories.record_run(
                state["active_trace_id"],
                "evidence",
                started=started,
                prior_context={"case_id": state["case_id"], "stage": state.get("stage")},
                decision={"next_step": "triage", "reason": "Evidence was retrieved within limits."},
                tool_name="list_evidence",
                tool_arguments={"case_id": state["case_id"]},
                tool_result={"evidence_ids": result["evidence_ids"]},
            )
            return result

        def triage(state: GraphState) -> GraphState:
            started = time.monotonic()
            case_id = state["case_id"]
            claim = self.store.get_record("claims", "claim_id", case_id)
            if claim is None:
                raise ToolNotFoundError("case was not found")
            baseline = triage_with_rules(
                claim,
                self.store.evidence_map(case_id, max_results=self.limits.max_retrieved_evidence),
            )
            if self.agent is not None:
                model_result = self.agent.run(
                    trace_id=state["active_trace_id"],
                    case_id=case_id,
                    review={
                        "decision": "initial_triage",
                        "reason": (
                            "Classify this claim for human review from the authorized records."
                        ),
                    },
                    actor_id="workflow_agent",
                )
                result = baseline.model_copy(
                    update={
                        "category": TriageCategory(model_result["action"]),
                        "score": model_result["score"],
                        "evidence_ids": sorted(
                            set(baseline.evidence_ids) | set(model_result["evidence_ids"])
                        ),
                        "model_version": f"{model_result['provider']}:{model_result['model']}",
                    }
                )
            else:
                result = baseline
            output = {"stage": "brief", "triage": result.model_dump(mode="json")}
            self.trajectories.record_run(
                state["active_trace_id"],
                "triage",
                started=started,
                prior_context={"case_id": case_id, "evidence_ids": state.get("evidence_ids", [])},
                decision={"category": result.category, "score": result.score},
                run_type="workflow",
                tool_arguments={"case_id": case_id},
                tool_result=output["triage"],
            )
            return output

        def brief(state: GraphState) -> GraphState:
            started = time.monotonic()
            triage_result = state["triage"]
            output = {
                "stage": "pending_review",
                "brief": {
                    "case_id": state["case_id"],
                    "category": triage_result["category"],
                    "score": triage_result["score"],
                    "indicator_ids": [item["indicator_id"] for item in triage_result["indicators"]],
                    "evidence_ids": triage_result["evidence_ids"],
                },
            }
            self.trajectories.record_run(
                state["active_trace_id"],
                "brief",
                started=started,
                prior_context={"case_id": state["case_id"], "category": triage_result["category"]},
                decision={
                    "next_step": "human_review",
                    "reason": "A human owns the claim decision.",
                },
                tool_result=output["brief"],
            )
            return output

        def review(state: GraphState) -> GraphState:
            response = interrupt(
                {
                    "case_id": state["case_id"],
                    "stage": "pending_review",
                    "brief": state["brief"],
                    "allowed_decisions": [
                        "approve_referral",
                        "reject_referral",
                        "request_information",
                    ],
                }
            )
            review_started = time.monotonic()
            context = ToolContext(
                actor_id=response["actor_id"],
                roles=frozenset(response["roles"]),
                correlation_id=response["correlation_id"],
            )
            saved = self.registry.execute(
                "save_review",
                {
                    "case_id": state["case_id"],
                    "decision": response["decision"],
                    "reason": response["reason"],
                    "idempotency_key": response["idempotency_key"],
                },
                context,
            )
            self.trajectories.record_run(
                response["trace_id"],
                "human_review",
                run_type="human_input",
                prior_context={"case_id": state["case_id"], "brief": state["brief"]},
                decision={"decision": response["decision"], "reason": response["reason"]},
                tool_name="save_review",
                tool_arguments={"case_id": state["case_id"], "decision": response["decision"]},
                tool_result={
                    "review_id": saved["review"]["review_id"],
                    "replayed": saved["idempotent_replay"],
                },
                started=review_started,
            )
            return {
                "stage": "post_review",
                "review": saved["review"],
                "active_trace_id": response["trace_id"],
            }

        def post_review(state: GraphState) -> GraphState:
            post_review_started = time.monotonic()
            if self.agent is not None:
                followup = self.agent.run(
                    trace_id=state["active_trace_id"],
                    case_id=state["case_id"],
                    review=state["review"],
                    actor_id=state["review"]["reviewer_id"],
                )
            elif os.getenv("CLAIMTRIAGE_TEST_MODE") == "1":
                followup = self._build_followup(state["case_id"], state["review"])
            else:
                raise AgentConfigurationError(
                    self.agent_configuration_error or "real LLM configuration is required"
                )
            self.trajectories.record_run(
                state["active_trace_id"],
                "post_review_action",
                prior_context={
                    "case_id": state["case_id"],
                    "review_id": state["review"]["review_id"],
                    "decision": state["review"]["decision"],
                },
                decision={
                    "action": followup["action"],
                    "reason": "Continue from the reviewer decision using authorized local records.",
                },
                run_type="workflow",
                tool_arguments={"case_id": state["case_id"]},
                tool_result=followup,
                started=post_review_started,
            )
            return {"stage": "complete", "agent_followup": followup}

        builder.add_node("intake", intake)
        builder.add_node("evidence", evidence)
        builder.add_node("triage", triage)
        builder.add_node("brief", brief)
        builder.add_node("review", review)
        builder.add_node("post_review", post_review)
        builder.add_edge(START, "intake")
        builder.add_edge("intake", "evidence")
        builder.add_edge("evidence", "triage")
        builder.add_edge("triage", "brief")
        builder.add_edge("brief", "review")
        builder.add_edge("review", "post_review")
        builder.add_edge("post_review", END)
        return builder.compile(checkpointer=self._checkpointer)

    def start(self, case_id: str) -> dict[str, Any]:
        """Run a new case to the durable reviewer interrupt."""
        with TRACER.start_as_current_span("claimtriagelab.workflow.start") as span:
            set_common_attributes(span, correlation_id=self.thread_id(case_id), operation="start")
            span.set_attribute("claimtriagelab.workflow_version", WORKFLOW_VERSION)
            existing = self.graph.get_state(self._config(case_id))
            if existing.values:
                return self.status(case_id)
            trace_id = self.trajectories.start_trace(
                self.thread_id(case_id),
                case_id,
                "initial_triage",
                "Triage the claim for human review.",
            )
            self.graph.invoke(
                {
                    "case_id": case_id,
                    "stage": "intake",
                    "version": WORKFLOW_VERSION,
                    "resource_limits": self.limits.to_dict(),
                    "active_trace_id": trace_id,
                },
                config=self._config(case_id),
            )
            state = self.status(case_id)
            self.trajectories.finish_trace(
                trace_id,
                "awaiting_human",
                {"stage": state["stage"], "brief": state.get("brief", {})},
            )
            context = state.get("narrative_context", {})
            span.set_attribute(
                "claimtriagelab.context.estimated_tokens", context.get("estimated_tokens", 0)
            )
            span.set_attribute("claimtriagelab.status", state["stage"])
            return state

    def resume(
        self,
        case_id: str,
        *,
        actor_id: str,
        roles: frozenset[str],
        decision: str,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Resume a paused case after checking authority at the service boundary."""
        with TRACER.start_as_current_span("claimtriagelab.workflow.resume") as span:
            set_common_attributes(span, correlation_id=correlation_id, operation="resume")
            span.set_attribute("claimtriagelab.workflow_version", WORKFLOW_VERSION)
            if "reviewer" not in roles:
                span.set_attribute("claimtriagelab.status", "denied")
                raise UnauthorizedToolError("actor cannot resume a pending review")
            self._validate_review_reason(decision, reason)
            current = self.status(case_id)
            stage = current.get("stage")
            if stage not in {"pending_review", "post_review"}:
                raise ValueError("case is not pending review")
            trace_id = self.trajectories.start_trace(
                self.thread_id(case_id),
                case_id,
                "review_continuation",
                f"Apply reviewer decision: {decision}",
            )
            try:
                if stage == "post_review":
                    persisted_review = current["review"]
                    self.trajectories.record_run(
                        trace_id,
                        "human_review",
                        run_type="human_input",
                        prior_context={"case_id": case_id, "recovery": True},
                        decision={
                            "decision": persisted_review["decision"],
                            "reason": persisted_review["reason"],
                        },
                        tool_name="save_review",
                        tool_arguments={"case_id": case_id},
                        tool_result={
                            "review_id": persisted_review["review_id"],
                            "replayed": True,
                        },
                    )
                    self.graph.update_state(
                        self._config(case_id),
                        {"active_trace_id": trace_id},
                        as_node="review",
                    )
                    self.graph.invoke(None, config=self._config(case_id))
                else:
                    self.graph.invoke(
                        Command(
                            resume={
                                "actor_id": actor_id,
                                "roles": sorted(roles),
                                "decision": decision,
                                "reason": reason,
                                "idempotency_key": idempotency_key,
                                "correlation_id": correlation_id,
                                "trace_id": trace_id,
                            }
                        ),
                        config=self._config(case_id),
                    )
            except Exception as error:
                self.trajectories.record_run(
                    trace_id,
                    "execution_failure",
                    run_type="evaluator",
                    prior_context={"case_id": case_id},
                    decision={"recoverable": True},
                    tool_result={"error_type": type(error).__name__},
                    status="error",
                    error_code="agent_execution_failed",
                )
                self.trajectories.finish_trace(
                    trace_id,
                    "failed",
                    {"stage": "pending_review", "error": "agent_execution_failed"},
                )
                raise
            state = self.status(case_id)
            self.trajectories.finish_trace(
                trace_id,
                "complete",
                {"stage": state["stage"], "agent_followup": state.get("agent_followup", {})},
            )
            span.set_attribute("claimtriagelab.status", state["stage"])
            return state

    def _build_followup(self, case_id: str, review: dict[str, Any]) -> dict[str, Any]:
        """Create a bounded continuation from a human decision without fabricating evidence."""
        decision = review["decision"]
        if decision != "request_information":
            action = (
                "prepare_referral_handoff"
                if decision == "approve_referral"
                else "record_no_referral"
            )
            return {
                "action": action,
                "summary": "The decision was recorded and a handoff summary was prepared.",
                "review_id": review["review_id"],
                "external_action_taken": False,
            }
        claim = self.store.get_record("claims", "claim_id", case_id) or {}
        policy = self.store.get_record("policies", "policy_id", claim.get("policy_id", "")) or {}
        evidence = self.store.evidence_records(case_id)
        fields = {str(item.get("field_name", "")): item for item in evidence}
        missing = [field for field, item in fields.items() if item.get("value") in {None, ""}]
        reason_lower = review["reason"].lower()
        requested_terms = {
            "repair estimate": "repair_estimate",
            "police report": "police_report",
            "incident report": "police_report",
            "photo": "incident_photos",
            "invoice": "invoice",
        }
        for phrase, field in requested_terms.items():
            if phrase in reason_lower and (field not in fields or not fields[field].get("value")):
                missing.append(field)
        missing = sorted(set(missing))
        return {
            "action": "collect_information",
            "summary": (
                "Authorized records were checked and an evidence collection plan was prepared."
            ),
            "review_id": review["review_id"],
            "sources_checked": {
                "claim_id": case_id,
                "policy_id": claim.get("policy_id"),
                "policy_found": bool(policy),
                "evidence_ids": [item.get("evidence_id") for item in evidence],
            },
            "missing_information": missing,
            "collection_checklist": [
                f"Obtain and verify: {field.replace('_', ' ')}." for field in missing
            ]
            or ["Clarify the reviewer's request and attach the supporting document."],
            "public_web_used": False,
            "external_action_taken": False,
        }

    def follow_up_review(
        self,
        case_id: str,
        *,
        actor_id: str,
        decision: str,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Append a later human review and execute the same post-review continuation."""
        self._validate_review_reason(decision, reason)
        trace_id = self.trajectories.start_trace(
            self.thread_id(case_id),
            case_id,
            "review_continuation",
            f"Apply follow-up reviewer decision: {decision}",
        )
        review_started = time.monotonic()
        saved = self.registry.execute(
            "save_review",
            {
                "case_id": case_id,
                "decision": decision,
                "reason": reason,
                "idempotency_key": idempotency_key,
            },
            ToolContext(actor_id, frozenset({"reviewer"}), correlation_id),
        )
        review = saved["review"]
        self.trajectories.record_run(
            trace_id,
            "human_review",
            run_type="human_input",
            prior_context={"case_id": case_id},
            decision={"decision": decision, "reason": reason},
            tool_name="save_review",
            tool_arguments={"case_id": case_id, "decision": decision},
            tool_result={
                "review_id": review["review_id"],
                "replayed": saved["idempotent_replay"],
            },
            started=review_started,
        )
        post_review_started = time.monotonic()
        if self.agent is not None:
            followup = self.agent.run(
                trace_id=trace_id,
                case_id=case_id,
                review=review,
                actor_id=actor_id,
            )
        elif os.getenv("CLAIMTRIAGE_TEST_MODE") == "1":
            followup = self._build_followup(case_id, review)
        else:
            raise AgentConfigurationError(
                self.agent_configuration_error or "real LLM configuration is required"
            )
        self.trajectories.record_run(
            trace_id,
            "post_review_action",
            prior_context={"case_id": case_id, "review_id": review["review_id"]},
            decision={"action": followup["action"]},
            tool_name="inspect_case_evidence",
            tool_arguments={"case_id": case_id},
            tool_result=followup,
            started=post_review_started,
        )
        self.trajectories.finish_trace(trace_id, "complete", {"agent_followup": followup})
        return followup

    def status(self, case_id: str) -> dict[str, Any]:
        """Return the latest persisted state without advancing the graph."""
        snapshot = self.graph.get_state(self._config(case_id))
        if not snapshot.values:
            raise ToolNotFoundError("workflow was not found")
        state = dict(snapshot.values)
        state["paused"] = bool(snapshot.interrupts)
        state["thread_id"] = self.thread_id(case_id)
        return state

    def checkpoint_history(self, case_id: str) -> list[dict[str, Any]]:
        """Return persisted checkpoint values from newest to oldest for replay inspection."""
        return [
            dict(snapshot.values)
            for snapshot in self.graph.get_state_history(self._config(case_id))
        ]
