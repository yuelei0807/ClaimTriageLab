"""LLM-as-a-judge evaluation for historical error-recovery traces."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, model_validator

from claimtriagelab.trajectory import TrajectoryStore


class TraceGrade(BaseModel):
    trace_id: str
    score: int = Field(ge=1, le=5)
    error_detected: bool
    recovered: bool
    rationale: str = Field(min_length=10, max_length=600)
    evidence_run_ids: list[str] = Field(default_factory=list)


class JudgeResponse(BaseModel):
    grades: list[TraceGrade]

    @model_validator(mode="after")
    def unique_trace_ids(self) -> JudgeResponse:
        ids = [grade.trace_id for grade in self.grades]
        if len(ids) != len(set(ids)):
            raise ValueError("judge returned duplicate trace IDs")
        return self


def _latest_trace_ids(database_path: Path, limit: int) -> list[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """SELECT trace_id FROM agent_traces
            ORDER BY started_at DESC, rowid DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    # Present the selected history in chronological order.
    return [str(row[0]) for row in reversed(rows)]


def _compact_trace(store: TrajectoryStore, trace_id: str) -> dict[str, Any]:
    trace = store.get_trace(trace_id)
    if trace is None:
        raise ValueError(f"trace not found: {trace_id}")
    runs = store.runs_for_trace(trace_id)
    evaluations = store.evaluations_for_trace(trace_id)

    def shortened(value: Any) -> Any:
        if isinstance(value, str):
            return value[:180]
        if isinstance(value, list):
            return [shortened(item) for item in value[:5]]
        return value

    run_sequence = [f"{run['step_name']}:{run['status']}" for run in runs]
    compact_runs = []
    for run in runs:
        if run["status"] == "success" and run["step_name"] not in {
            "grounding_validation",
            "post_review_action",
        }:
            continue
        decision = run["decision"]
        result = run["tool_result"]
        recovery_facts: dict[str, Any] = {}
        if isinstance(decision, dict):
            for key in ("accepted", "reason", "next_step", "decision", "category"):
                if key in decision:
                    recovery_facts[key] = shortened(decision[key])
        if isinstance(result, dict):
            for key in ("accepted", "errors", "stage", "action", "error"):
                if key in result:
                    recovery_facts[f"result_{key}"] = shortened(result[key])
        compact_runs.append(
            {
                "id": run["run_id"],
                "step": run["step_name"],
                "status": run["status"],
                **({"error": run["error_code"]} if run["error_code"] else {}),
                **({"facts": recovery_facts} if recovery_facts else {}),
            }
        )
    compact_outcome: dict[str, Any] = {}
    if isinstance(trace["outcome"], dict):
        compact_outcome["stage"] = trace["outcome"].get("stage")
        followup = trace["outcome"].get("agent_followup")
        if isinstance(followup, dict):
            compact_outcome["agent_followup"] = {
                key: shortened(followup.get(key))
                for key in ("action", "summary", "evidence_ids")
                if key in followup
            }
    return {
        "trace_id": trace_id,
        "task_type": trace["task_type"],
        "status": trace["status"],
        "sequence": run_sequence,
        "recovery_runs": compact_runs,
        "deterministic_checks": [
            {
                "name": item["evaluator_name"],
                "severity": item["severity"],
                "message": shortened(item["message"]),
            }
            for item in evaluations
        ],
        "outcome": compact_outcome,
    }


def _judge_prompt(traces: list[dict[str, Any]]) -> list[dict[str, str]]:
    rubric = """You are an independent production reliability evaluator. Grade ERROR recovery
for every supplied agent trace on an integer scale from 1 to 5. Base the grade only on the
recorded runs, statuses, deterministic checks, and outcome.

Rubric:
1 = an error was missed, the workflow failed without a useful recovery, or the final result is
    wrong.
2 = the error was detected but recovery failed or the result remains materially unreliable.
3 = partial recovery; the workflow continued but evidence of a correct final result is incomplete.
4 = successful, validated recovery with a minor weakness or avoidable retry. A clean trace with no
    error may also receive 4 when safeguards ran and no recovery was needed.
5 = explicit error detection, correction, retry, and a fully validated grounded result. A trace with
    no error can receive 5 only when the record strongly demonstrates robust safeguards.

Treat status=retry as a correction request, not a terminal failure. A later accepted validation and
successful workflow output demonstrate recovery. Each recovery_run uses id, step, and status;
optional error and facts hold recovery details. Use only run IDs present in that trace as evidence.
Return JSON only with this shape:
{"grades":[{"trace_id":"trace_...","score":1,"error_detected":true,
"recovered":false,"rationale":"...","evidence_run_ids":["run_..."]}]}
Return exactly one grade for every supplied trace and preserve each trace_id exactly."""
    return [
        {"role": "system", "content": rubric},
        {"role": "user", "content": json.dumps({"traces": traces}, separators=(",", ":"))},
    ]


def judge_historical_traces(
    database_path: Path,
    *,
    limit: int = 10,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Ask Groq to grade exactly ``limit`` persisted traces and validate its response."""
    if limit != 10:
        raise ValueError("Task 9 evaluation requires exactly 10 traces")
    trace_ids = _latest_trace_ids(database_path, limit)
    if len(trace_ids) != limit:
        raise ValueError(f"expected 10 persisted traces, found {len(trace_ids)}")
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for the real LLM judge")
    model = os.getenv("CLAIMTRIAGE_JUDGE_MODEL", "openai/gpt-oss-20b").strip()
    store = TrajectoryStore(database_path)
    traces = [_compact_trace(store, trace_id) for trace_id in trace_ids]
    payload: dict[str, Any] = {
        "model": model,
        "messages": _judge_prompt(traces),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 2000,
    }
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"
    owns_client = client is None
    http = client or httpx.Client(timeout=90.0)
    try:
        response = http.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        judged = JudgeResponse.model_validate_json(content)
    finally:
        if owns_client:
            http.close()
    returned_ids = {grade.trace_id for grade in judged.grades}
    expected_ids = set(trace_ids)
    if returned_ids != expected_ids or len(judged.grades) != limit:
        missing = sorted(expected_ids - returned_ids)
        unexpected = sorted(returned_ids - expected_ids)
        raise ValueError(f"judge trace set mismatch; missing={missing}, unexpected={unexpected}")
    valid_runs = {
        trace["trace_id"]: {run["id"] for run in trace["recovery_runs"]} for trace in traces
    }
    for grade in judged.grades:
        invalid = set(grade.evidence_run_ids) - valid_runs[grade.trace_id]
        if invalid:
            raise ValueError(f"judge cited unknown run IDs for {grade.trace_id}: {sorted(invalid)}")
    ordered = sorted(judged.grades, key=lambda grade: trace_ids.index(grade.trace_id))
    scores = [grade.score for grade in ordered]
    return {
        "evaluation": "error_recovery_llm_judge_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "groq",
        "model": model,
        "trace_count": len(ordered),
        "mean_score": round(sum(scores) / len(scores), 2),
        "score_distribution": dict(sorted(Counter(str(score) for score in scores).items())),
        "grades": [grade.model_dump() for grade in ordered],
    }
