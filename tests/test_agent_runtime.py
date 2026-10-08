"""Real provider protocol and model-selected function execution tests."""

from pathlib import Path

from claimtriagelab.agent.runtime import ModelDrivenAgent, ModelSettings
from claimtriagelab.tools.registry import ToolRegistry
from claimtriagelab.tools.store import ToolStore
from claimtriagelab.trajectory import TrajectoryStore


class Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class EvidenceIndex:
    def index_case(self, case_id: str, records: list[dict]) -> None:
        return None

    def search(self, case_id: str, query: str, limit: int = 5) -> list[dict]:
        return [
            {
                "evidence_id": "ev_report",
                "field_name": "police_report",
                "text": "police_report: No",
                "score": 0.9,
            }
        ]


def test_model_tool_call_executes_real_registry_function(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite3"
    store = ToolStore(database)
    store.seed_case(
        {"claim_id": "claim_agent", "policy_id": "policy_agent", "police_report": ""},
        {"policy_id": "policy_agent", "status": "active"},
        [],
    )
    trajectories = TrajectoryStore(database)
    trace_id = trajectories.start_trace(
        "claim:claim_agent", "claim_agent", "review_continuation", "model test"
    )
    responses = iter(
        [
            Response(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_claim",
                                            "arguments": '{"claim_id":"claim_agent"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                }
            ),
            Response(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": (
                                    '{"action":"collect_information","summary":"Need report",'
                                    '"missing_information":["police report"],'
                                    '"collection_checklist":["Obtain police report"],'
                                    '"evidence_ids":[]}'
                                ),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 15},
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "claimtriagelab.agent.runtime.httpx.post", lambda *args, **kwargs: next(responses)
    )
    agent = ModelDrivenAgent(
        ModelSettings("groq", "openai/gpt-oss-20b", "test-key"),
        ToolRegistry(store),
        trajectories,
    )
    outcome = agent.run(
        trace_id=trace_id,
        case_id="claim_agent",
        review={"decision": "request_information", "reason": "Clarify missing police report"},
        actor_id="reviewer",
    )
    assert outcome["action"] == "collect_information"
    runs = trajectories.runs_for_trace(trace_id)
    assert [run["run_type"] for run in runs] == [
        "generation",
        "tool",
        "generation",
        "evaluator",
    ]
    assert runs[1]["tool_name"] == "get_claim"
    assert store.audit_events()[0]["tool_name"] == "get_claim"


def test_ungrounded_answer_is_retried_and_correction_is_preserved(
    monkeypatch, tmp_path: Path
) -> None:
    database = tmp_path / "grounding.sqlite3"
    store = ToolStore(database)
    store.seed_case(
        {"claim_id": "claim_grounding", "policy_id": "policy_grounding"},
        {"policy_id": "policy_grounding", "status": "active"},
        [{"evidence_id": "ev_report", "field_name": "police_report", "value": "No"}],
    )
    trajectories = TrajectoryStore(database)
    trace_id = trajectories.start_trace(
        "claim:claim_grounding", "claim_grounding", "review_continuation", "grounding test"
    )
    responses = iter(
        [
            Response(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "search_1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_evidence",
                                            "arguments": (
                                                '{"case_id":"claim_grounding",'
                                                '"query":"missing police report"}'
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                }
            ),
            Response(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": ""},
                        }
                    ]
                }
            ),
            Response(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": (
                                    '{"action":"request_information","summary":"Need photos",'
                                    '"missing_information":["medical records"],'
                                    '"collection_checklist":["Obtain medical records"],'
                                    '"evidence_ids":[],"score":null}'
                                ),
                            },
                        }
                    ]
                }
            ),
            Response(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": (
                                    '{"action":"request_information","summary":"Need report",'
                                    '"missing_information":["police report"],'
                                    '"collection_checklist":["Obtain police report"],'
                                    '"evidence_ids":["ev_report"],"score":null}'
                                ),
                            },
                        }
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "claimtriagelab.agent.runtime.httpx.post", lambda *args, **kwargs: next(responses)
    )
    agent = ModelDrivenAgent(
        ModelSettings("groq", "openai/gpt-oss-20b", "test-key"),
        ToolRegistry(store),
        trajectories,
        EvidenceIndex(),  # type: ignore[arg-type]
    )
    outcome = agent.run(
        trace_id=trace_id,
        case_id="claim_grounding",
        review={"decision": "request_information", "reason": "Obtain the missing police report"},
        actor_id="reviewer",
    )
    validators = [
        run
        for run in trajectories.runs_for_trace(trace_id)
        if run["step_name"] == "grounding_validation"
    ]
    output_validators = [
        run
        for run in trajectories.runs_for_trace(trace_id)
        if run["step_name"] == "output_validation"
    ]
    assert [run["decision"]["accepted"] for run in validators] == [False, True]
    assert len(output_validators) == 1
    assert outcome["evidence_ids"] == ["ev_report"]
