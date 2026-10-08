"""Task 9 LLM-as-a-judge contract tests."""

import json
from pathlib import Path

import httpx
import pytest

from claimtriagelab.evaluation import judge_historical_traces
from claimtriagelab.trajectory import TrajectoryStore


def _ten_trace_database(path: Path) -> tuple[list[str], list[str]]:
    store = TrajectoryStore(path)
    trace_ids = []
    run_ids = []
    for index in range(10):
        trace_id = store.start_trace(
            f"thread:{index}", f"case_{index}", "review_continuation", "Recover safely"
        )
        run_id = store.record_run(
            trace_id,
            "post_review_action",
            run_type="workflow",
            prior_context={"case_id": f"case_{index}"},
            decision={"accepted": True},
            tool_result={"stage": "complete"},
        )
        store.finish_trace(trace_id, "complete", {"stage": "complete"})
        trace_ids.append(trace_id)
        run_ids.append(run_id)
    return trace_ids, run_ids


def test_llm_judge_validates_and_aggregates_ten_traces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "traces.sqlite3"
    trace_ids, run_ids = _ten_trace_database(database)

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        assert sent["response_format"] == {"type": "json_object"}
        grades = [
            {
                "trace_id": trace_id,
                "score": 4,
                "error_detected": False,
                "recovered": True,
                "rationale": "The workflow completed and deterministic safeguards were recorded.",
                "evidence_run_ids": [run_id],
            }
            for trace_id, run_id in zip(trace_ids, run_ids, strict=True)
        ]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"grades": grades})}}]},
        )

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge_historical_traces(database, client=client)
    assert result["trace_count"] == 10
    assert result["mean_score"] == 4.0
    assert result["score_distribution"] == {"4": 10}


def test_llm_judge_requires_exactly_ten_persisted_traces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "traces.sqlite3"
    TrajectoryStore(database)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with pytest.raises(ValueError, match="expected 10"):
        judge_historical_traces(database)
