"""Durable local execution trajectories and deterministic diagnostics."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class TrajectoryStore:
    """Store application-level threads, traces, runs, and evaluation findings."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_threads (
                    thread_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_traces (
                    trace_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    user_intent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (thread_id) REFERENCES agent_threads(thread_id)
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    trace_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    step_name TEXT NOT NULL,
                    run_type TEXT NOT NULL,
                    prior_context_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    tool_name TEXT,
                    tool_arguments_json TEXT NOT NULL,
                    tool_result_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    FOREIGN KEY (trace_id) REFERENCES agent_traces(trace_id)
                );
                CREATE TABLE IF NOT EXISTS trajectory_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    run_id TEXT,
                    evaluator_name TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    score REAL NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (trace_id) REFERENCES agent_traces(trace_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_traces_thread
                    ON agent_traces(thread_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_trace
                    ON agent_runs(trace_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_trajectory_evaluations_trace
                    ON trajectory_evaluations(trace_id, created_at);
                """
            )

    def ensure_thread(self, thread_id: str, case_id: str) -> None:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_threads VALUES (?, ?, 'active', ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET updated_at = excluded.updated_at""",
                (thread_id, case_id, now, now),
            )

    def start_trace(self, thread_id: str, case_id: str, task_type: str, intent: str) -> str:
        self.ensure_thread(thread_id, case_id)
        trace_id = f"trace_{uuid4().hex}"
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO agent_traces VALUES (?, ?, ?, ?, 'running', '{}', ?, NULL)",
                (trace_id, thread_id, task_type, intent, _now()),
            )
        return trace_id

    def record_run(
        self,
        trace_id: str,
        step_name: str,
        *,
        run_type: str = "node",
        prior_context: dict[str, Any] | None = None,
        decision: dict[str, Any] | None = None,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        tool_result: Any = None,
        status: str = "success",
        error_code: str | None = None,
        started: float | None = None,
        parent_run_id: str | None = None,
    ) -> str:
        run_id = f"run_{uuid4().hex}"
        duration = max(0.0, (time.monotonic() - started) * 1000) if started else 0.0
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_runs
                (run_id, trace_id, parent_run_id, step_name, run_type, prior_context_json,
                 decision_json, tool_name, tool_arguments_json, tool_result_json, status,
                 error_code, started_at, completed_at, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    trace_id,
                    parent_run_id,
                    step_name,
                    run_type,
                    _json(prior_context or {}),
                    _json(decision or {}),
                    tool_name,
                    _json(tool_arguments or {}),
                    _json(tool_result),
                    status,
                    error_code,
                    now,
                    now,
                    round(duration, 3),
                ),
            )
        return run_id

    def finish_trace(self, trace_id: str, status: str, outcome: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE agent_traces
                SET status = ?, outcome_json = ?, completed_at = ? WHERE trace_id = ?""",
                (status, _json(outcome), _now(), trace_id),
            )
        self.evaluate(trace_id)
        from claimtriagelab.langfuse_export import LangfuseExporter

        exporter = (
            None
            if os.getenv("CLAIMTRIAGE_TEST_MODE") == "1"
            else LangfuseExporter.from_environment()
        )
        if exporter is not None:
            trace = self.get_trace(trace_id)
            if trace is not None:
                try:
                    exporter.export(trace, self.runs_for_trace(trace_id))
                except Exception as error:
                    with self.connect() as connection:
                        connection.execute(
                            """INSERT INTO trajectory_evaluations
                            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)""",
                            (
                                f"eval_{uuid4().hex}",
                                trace_id,
                                "langfuse_export",
                                "warning",
                                0.0,
                                "The local trace completed, but Langfuse export failed.",
                                _json({"error_type": type(error).__name__}),
                                _now(),
                            ),
                        )

    def evaluate(self, trace_id: str) -> list[dict[str, Any]]:
        trace = self.get_trace(trace_id)
        if trace is None:
            raise ValueError("trace was not found")
        runs = self.runs_for_trace(trace_id)
        required = {
            "initial_triage": ["intake", "evidence", "triage", "brief"],
            "review_continuation": ["human_review", "post_review_action"],
        }.get(trace["task_type"], [])
        names = [run["step_name"] for run in runs]
        ordered = all(name in names for name in required) and [
            names.index(name) for name in required
        ] == sorted(names.index(name) for name in required)
        failed_runs = [run for run in runs if run["status"] == "error"]
        retry_runs = [run for run in runs if run["status"] == "retry"]
        if failed_runs:
            run_severity, run_score = "fail", 0.0
            run_message = "At least one execution run failed."
        elif retry_runs:
            run_severity, run_score = "warning", 0.75
            run_message = "An evaluator requested correction and the trace recovered."
        else:
            run_severity, run_score = "pass", 1.0
            run_message = "All recorded runs completed successfully."
        checks = [
            (
                "required_step_sequence",
                "pass" if ordered else "fail",
                1.0 if ordered else 0.0,
                "Required execution steps are present and ordered."
                if ordered
                else "A required step is missing or out of order.",
                {"required": required, "observed": names},
            ),
            (
                "run_status",
                run_severity,
                run_score,
                run_message,
                {
                    "failed_run_ids": [run["run_id"] for run in failed_runs],
                    "retry_run_ids": [run["run_id"] for run in retry_runs],
                },
            ),
        ]
        thread = self.get_thread(trace["thread_id"])
        mismatched = [
            run["run_id"]
            for run in runs
            if run["prior_context"].get("case_id") not in {None, thread["case_id"]}
        ]
        checks.append(
            (
                "context_consistency",
                "pass" if not mismatched else "fail",
                1.0 if not mismatched else 0.0,
                "Run context remains attached to the thread case."
                if not mismatched
                else "Possible context drift: a run references another case.",
                {"mismatched_run_ids": mismatched},
            )
        )
        search_runs = [run for run in runs if run["tool_name"] == "search_evidence"]
        if search_runs:
            retrieved = {
                str(item["evidence_id"])
                for run in search_runs
                for item in (run["tool_result"] or [])
                if isinstance(item, dict) and item.get("evidence_id")
            }
            grounding_runs = [run for run in runs if run["step_name"] == "grounding_validation"]
            accepted = bool(grounding_runs and grounding_runs[-1]["decision"].get("accepted"))
            cited = {
                str(item)
                for item in (
                    grounding_runs[-1]["tool_result"].get("cited_evidence_ids", [])
                    if grounding_runs
                    else []
                )
            }
            policy_errors: list[str] = []
            if trace["task_type"] == "review_continuation":
                final_runs = [run for run in runs if run["step_name"] == "post_review_action"]
                human_runs = [run for run in runs if run["step_name"] == "human_review"]
                if final_runs and human_runs:
                    from claimtriagelab.agent.runtime import AgentOutcome, ModelDrivenAgent

                    final_payload = final_runs[-1]["tool_result"]
                    final_outcome = AgentOutcome.model_validate(
                        {key: final_payload.get(key) for key in AgentOutcome.model_fields}
                    )
                    grounding_text = str(human_runs[-1]["decision"].get("reason", ""))
                    grounding_text += " " + " ".join(
                        str(item.get("text", ""))
                        for run in search_runs
                        for item in (run["tool_result"] or [])
                        if isinstance(item, dict)
                    )
                    policy_errors = ModelDrivenAgent._grounding_errors(
                        final_outcome,
                        retrieved,
                        grounding_text,
                        str(human_runs[-1]["decision"].get("decision", "")),
                    )
            contract_errors = [
                error
                for error in policy_errors
                if error.startswith("score must") or "allowed category" in error
            ]
            grounding_policy_errors = [
                error for error in policy_errors if error not in contract_errors
            ]
            grounded = (
                accepted and bool(cited) and cited <= retrieved and not grounding_policy_errors
            )
            checks.append(
                (
                    "evidence_grounding",
                    "pass" if grounded else "fail",
                    1.0 if grounded else 0.0,
                    "The final model output cites retrieved evidence."
                    if grounded
                    else (
                        "The final model output has missing or invalid citations, or unsupported "
                        "claims."
                    ),
                    {
                        "retrieved_evidence_ids": sorted(retrieved),
                        "cited_evidence_ids": sorted(cited),
                        "final_grounding_validation_accepted": accepted,
                        "current_policy_errors": grounding_policy_errors,
                    },
                )
            )
            if trace["task_type"] == "review_continuation":
                checks.append(
                    (
                        "output_contract",
                        "pass" if not contract_errors else "fail",
                        1.0 if not contract_errors else 0.0,
                        "The final model output follows the post-review schema."
                        if not contract_errors
                        else "Output contract violation: " + "; ".join(contract_errors),
                        {"errors": contract_errors},
                    )
                )
        with self.connect() as connection:
            connection.execute("DELETE FROM trajectory_evaluations WHERE trace_id = ?", (trace_id,))
            for name, severity, score, message, details in checks:
                connection.execute(
                    "INSERT INTO trajectory_evaluations VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                    (
                        f"eval_{uuid4().hex}",
                        trace_id,
                        name,
                        severity,
                        score,
                        message,
                        _json(details),
                        _now(),
                    ),
                )
        return self.evaluations_for_trace(trace_id)

    @staticmethod
    def _decoded(row: sqlite3.Row, json_fields: tuple[str, ...]) -> dict[str, Any]:
        item = dict(row)
        for field in json_fields:
            item[field.removesuffix("_json")] = json.loads(item.pop(field))
        return item

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
        return self._decoded(row, ("outcome_json",)) if row else None

    def traces_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_traces WHERE thread_id = ? ORDER BY started_at", (thread_id,)
            ).fetchall()
        return [self._decoded(row, ("outcome_json",)) for row in rows]

    def runs_for_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs WHERE trace_id = ? ORDER BY sequence", (trace_id,)
            ).fetchall()
        return [
            self._decoded(
                row,
                ("prior_context_json", "decision_json", "tool_arguments_json", "tool_result_json"),
            )
            for row in rows
        ]

    def evaluations_for_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trajectory_evaluations WHERE trace_id = ? ORDER BY created_at",
                (trace_id,),
            ).fetchall()
        return [self._decoded(row, ("details_json",)) for row in rows]
