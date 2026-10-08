"""Real Groq/Gemini tool-calling runtime; no deterministic reasoning fallback."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from claimtriagelab.retrieval import QdrantEvidenceIndex
from claimtriagelab.retrieval.qdrant import QdrantConfigurationError
from claimtriagelab.tools.contracts import ToolContext
from claimtriagelab.tools.registry import ToolRegistry
from claimtriagelab.trajectory import TrajectoryStore


class AgentConfigurationError(RuntimeError):
    """Raised when a real inference or retrieval provider is unavailable."""


class AgentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2000)
    missing_information: list[str] = Field(default_factory=list, max_length=30)
    collection_checklist: list[str] = Field(default_factory=list, max_length=30)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    score: float | None = Field(default=None, ge=0, le=1)


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model: str
    api_key: str

    @classmethod
    def from_environment(cls) -> ModelSettings:
        provider = os.getenv("CLAIMTRIAGE_LLM_PROVIDER", "groq").lower()
        if provider == "groq":
            key = os.getenv("GROQ_API_KEY", "")
            model = os.getenv("CLAIMTRIAGE_LLM_MODEL", "openai/gpt-oss-20b")
        elif provider == "gemini":
            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
            model = os.getenv("CLAIMTRIAGE_LLM_MODEL", "gemini-2.5-flash")
        else:
            raise AgentConfigurationError("CLAIMTRIAGE_LLM_PROVIDER must be groq or gemini")
        if not key:
            raise AgentConfigurationError(
                f"{provider} API key is required for real agent execution"
            )
        return cls(provider, model, key)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_claim",
            "description": "Read the authorized synthetic claim record.",
            "parameters": {
                "type": "object",
                "properties": {"claim_id": {"type": "string"}},
                "required": ["claim_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy",
            "description": "Read the policy referenced by the claim.",
            "parameters": {
                "type": "object",
                "properties": {"policy_id": {"type": "string"}},
                "required": ["policy_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_evidence",
            "description": "Read one cited evidence record.",
            "parameters": {
                "type": "object",
                "properties": {"evidence_id": {"type": "string"}},
                "required": ["evidence_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_evidence",
            "description": (
                "Semantically search the authorized claim evidence in Qdrant. "
                "Use this to find records relevant to the reviewer's reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["case_id", "query"],
                "additionalProperties": False,
            },
        },
    },
]


SYSTEM_PROMPT = """You are an insurance claim review assistant operating only on synthetic data.
Use the supplied tools to inspect records before reaching a conclusion. Always use search_evidence
with a query derived from the task before returning your answer. Do not invent evidence, contact
anyone, or take an external action. Return only JSON with keys action, summary,
missing_information, collection_checklist, evidence_ids, score. Every factual conclusion and every
requested item must be supported by the review reason or retrieved evidence, and evidence_ids must
cite the retrieved records used. Do not claim that an item is missing merely because search did
not return it; absence must be explicit in a retrieved record or the review reason. For an
initial_triage task, action must be priority_review,
routine_review, or insufficient_information. In initial triage, score means referral priority risk:
priority_review requires 0.6 through 1, routine_review requires 0 through less than 0.6, and missing
required claim information requires insufficient_information. For a human review, score must be
null, and the human decision is authoritative. A request_information decision must produce a
grounded, concrete collection plan; other decisions produce a bounded handoff."""

GENERIC_GROUNDING_WORDS = {
    "additional",
    "collect",
    "detail",
    "detailed",
    "document",
    "documentation",
    "evidence",
    "information",
    "missing",
    "obtain",
    "required",
}
SENSITIVE_ASSERTION_WORDS = {
    "coverage",
    "fraud",
    "injury",
    "liability",
    "medical",
    "photo",
    "witness",
}


class ModelDrivenAgent:
    """Execute a bounded model-selected tool loop and record every real operation."""

    max_iterations = 8
    max_provider_attempts = 4

    def __init__(
        self,
        settings: ModelSettings,
        registry: ToolRegistry,
        trajectories: TrajectoryStore,
        evidence_index: QdrantEvidenceIndex | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.trajectories = trajectories
        self.evidence_index = evidence_index

    @classmethod
    def from_environment(
        cls, registry: ToolRegistry, trajectories: TrajectoryStore
    ) -> ModelDrivenAgent:
        settings = ModelSettings.from_environment()
        try:
            index = QdrantEvidenceIndex.from_environment()
        except QdrantConfigurationError:
            if os.getenv("CLAIMTRIAGE_TEST_MODE") == "1":
                index = None
            else:
                raise AgentConfigurationError(
                    "QDRANT_URL and QDRANT_API_KEY are required for semantic retrieval"
                ) from None
        return cls(settings, registry, trajectories, index)

    def run(
        self,
        *,
        trace_id: str,
        case_id: str,
        review: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        if self.evidence_index is not None:
            self.evidence_index.index_case(case_id, self.registry.store.evidence_records(case_id))
        if self.settings.provider == "gemini":
            return self._run_gemini(
                trace_id=trace_id,
                case_id=case_id,
                review=review,
                actor_id=actor_id,
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "case_id": case_id,
                        "human_decision": review["decision"],
                        "human_reason": review["reason"],
                    }
                ),
            },
        ]
        retrieved_ids: set[str] = set()
        grounding_text = review["reason"]
        for iteration in range(1, self.max_iterations + 1):
            started = time.monotonic()
            response = self._post_with_rate_limit_retry(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json={
                    "model": self.settings.model,
                    "messages": messages,
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "temperature": 0,
                    "max_completion_tokens": 1200,
                    **(
                        {"reasoning_effort": "low"}
                        if self.settings.model.startswith("openai/gpt-oss")
                        else {}
                    ),
                },
                timeout=30,
            )
            payload = response.json()
            message = payload["choices"][0]["message"]
            calls = message.get("tool_calls", [])
            self.trajectories.record_run(
                trace_id,
                f"model_reasoning_{iteration}",
                run_type="generation",
                prior_context={"case_id": case_id, "message_count": len(messages)},
                decision={"tool_calls": [call["function"]["name"] for call in calls]},
                tool_arguments={"provider": self.settings.provider, "model": self.settings.model},
                tool_result={
                    "finish_reason": payload["choices"][0].get("finish_reason"),
                    "usage": payload.get("usage", {}),
                },
                started=started,
            )
            messages.append(message)
            if not calls:
                content = (message.get("content") or "{}").strip()
                if content.startswith("```"):
                    content = content.removeprefix("```json").removeprefix("```")
                    content = content.removesuffix("```").strip()
                try:
                    outcome = AgentOutcome.model_validate_json(content)
                except (ValidationError, ValueError):
                    self.trajectories.record_run(
                        trace_id,
                        "output_validation",
                        run_type="evaluator",
                        prior_context={"case_id": case_id, "model_iteration": iteration},
                        decision={"accepted": False, "retry": True},
                        tool_result={
                            "error": "The model did not return the required JSON object.",
                            "finish_reason": payload["choices"][0].get("finish_reason"),
                        },
                        status="retry",
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was empty, truncated, or invalid. Return a "
                                "concise JSON object with every required key and no commentary."
                            ),
                        }
                    )
                    continue
                grounding_errors = self._grounding_errors(
                    outcome, retrieved_ids, grounding_text, review["decision"]
                )
                self.trajectories.record_run(
                    trace_id,
                    "grounding_validation",
                    run_type="evaluator",
                    prior_context={
                        "case_id": case_id,
                        "retrieved_evidence_ids": sorted(retrieved_ids),
                    },
                    decision={"accepted": not grounding_errors},
                    tool_result={
                        "errors": grounding_errors,
                        "cited_evidence_ids": outcome.evidence_ids,
                    },
                    status="success" if not grounding_errors else "retry",
                )
                if grounding_errors:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Correct the answer and return JSON only. Grounding validation "
                                f"found: {'; '.join(grounding_errors)}"
                            ),
                        }
                    )
                    continue
                return {
                    **outcome.model_dump(),
                    "provider": self.settings.provider,
                    "model": self.settings.model,
                    "external_action_taken": False,
                }
            for call in calls:
                name = call["function"]["name"]
                arguments = json.loads(call["function"]["arguments"])
                tool_started = time.monotonic()
                result = self._execute_tool(name, arguments, actor_id, trace_id, case_id)
                if name == "search_evidence":
                    retrieved_ids.update(
                        str(item["evidence_id"]) for item in result if item.get("evidence_id")
                    )
                    grounding_text += " " + " ".join(str(item.get("text", "")) for item in result)
                self.trajectories.record_run(
                    trace_id,
                    name,
                    run_type="tool",
                    prior_context={"case_id": case_id, "model_iteration": iteration},
                    decision={"selected_by_model": True},
                    tool_name=name,
                    tool_arguments=arguments,
                    tool_result=result,
                    started=tool_started,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": name,
                        "content": json.dumps(result, default=str),
                    }
                )
        raise RuntimeError("model exceeded the bounded tool-call iteration limit")

    def _post_with_rate_limit_retry(self, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, self.max_provider_attempts + 1):
            response = httpx.post(url, **kwargs)
            if getattr(response, "status_code", 200) != 429:
                response.raise_for_status()
                return response
            if attempt == self.max_provider_attempts:
                response.raise_for_status()
            retry_header = response.headers.get("retry-after", "")
            try:
                delay = float(retry_header)
            except ValueError:
                match = re.search(r"try again in ([0-9.]+)s", response.text, re.IGNORECASE)
                delay = float(match.group(1)) if match else float(2**attempt)
            time.sleep(min(max(delay, 1.0), 45.0))
        raise RuntimeError("provider retry loop exited unexpectedly")

    @staticmethod
    def _grounding_errors(
        outcome: AgentOutcome,
        retrieved_ids: set[str],
        grounding_text: str,
        task: str,
    ) -> list[str]:
        errors: list[str] = []
        cited = set(outcome.evidence_ids)
        invalid = cited - retrieved_ids
        if invalid:
            errors.append(f"unknown evidence IDs: {', '.join(sorted(invalid))}")
        if retrieved_ids and not cited:
            errors.append("evidence_ids must cite at least one retrieved record")
        if task == "initial_triage" and outcome.action not in {
            "priority_review",
            "routine_review",
            "insufficient_information",
        }:
            errors.append("initial triage action is not an allowed category")
        if task == "initial_triage":
            if outcome.action == "priority_review" and (
                outcome.score is None or outcome.score < 0.6
            ):
                errors.append("priority_review requires a priority risk score of at least 0.6")
            if outcome.action == "routine_review" and (
                outcome.score is None or outcome.score >= 0.6
            ):
                errors.append("routine_review requires a priority risk score below 0.6")
            if outcome.missing_information and outcome.action != "insufficient_information":
                errors.append("missing required information requires insufficient_information")

        def tokens(value: str) -> set[str]:
            normalized = set()
            for token in re.findall(r"[a-z0-9]+", value.lower()):
                if token.startswith("photograph"):
                    token = "photo"
                elif token.startswith("injur"):
                    token = "injury"
                elif token.startswith("witness"):
                    token = "witness"
                elif token.endswith("s") and len(token) > 4:
                    token = token[:-1]
                if len(token) >= 4:
                    normalized.add(token)
            return normalized

        source_tokens = tokens(grounding_text)
        requested_items = outcome.missing_information + outcome.collection_checklist
        for item in requested_items:
            item_tokens = tokens(item) - GENERIC_GROUNDING_WORDS
            overlap = item_tokens & source_tokens
            required_matches = 1 if len(item_tokens) <= 1 else 2
            if item_tokens and len(overlap) < required_matches:
                errors.append(f"unsupported requested item: {item}")
        unsupported_assertions = (
            tokens(outcome.summary) & SENSITIVE_ASSERTION_WORDS
        ) - source_tokens
        if unsupported_assertions:
            errors.append(
                "unsupported summary assertions: " + ", ".join(sorted(unsupported_assertions))
            )
        if task != "initial_triage" and outcome.score is not None:
            errors.append("score must be null for post-review continuation")
        return errors

    def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        actor_id: str,
        trace_id: str,
        case_id: str,
    ) -> Any:
        if name != "search_evidence":
            return self.registry.execute(
                name,
                arguments,
                ToolContext(actor_id, frozenset({"reviewer"}), trace_id, timeout_ms=5_000),
            )
        if self.evidence_index is None:
            raise AgentConfigurationError("Qdrant semantic retrieval is unavailable")
        if arguments.get("case_id") != case_id:
            raise ValueError("semantic search is restricted to the active case")
        started = time.monotonic()
        try:
            result = self.evidence_index.search(
                case_id, str(arguments["query"]), int(arguments.get("limit", 5))
            )
        except Exception:
            self.registry.store.audit(
                correlation_id=trace_id,
                actor_id=actor_id,
                tool_name=name,
                status="error",
                arguments=arguments,
                error_code="retrieval_error",
                duration_ms=(time.monotonic() - started) * 1000,
                attempt_count=1,
            )
            raise
        self.registry.store.audit(
            correlation_id=trace_id,
            actor_id=actor_id,
            tool_name=name,
            status="success",
            arguments=arguments,
            error_code=None,
            duration_ms=(time.monotonic() - started) * 1000,
            attempt_count=1,
        )
        return result

    def _run_gemini(
        self,
        *,
        trace_id: str,
        case_id: str,
        review: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        declarations = [item["function"] for item in TOOLS]
        contents: list[dict[str, Any]] = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": json.dumps(
                            {
                                "case_id": case_id,
                                "human_decision": review["decision"],
                                "human_reason": review["reason"],
                            }
                        )
                    }
                ],
            }
        ]
        retrieved_ids: set[str] = set()
        grounding_text = review["reason"]
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.model}:generateContent"
        )
        for iteration in range(1, self.max_iterations + 1):
            started = time.monotonic()
            response = self._post_with_rate_limit_retry(
                endpoint,
                params={"key": self.settings.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": contents,
                    "tools": [{"functionDeclarations": declarations}],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=30,
            )
            payload = response.json()
            candidate = payload["candidates"][0]
            content = candidate["content"]
            calls = [part["functionCall"] for part in content["parts"] if "functionCall" in part]
            self.trajectories.record_run(
                trace_id,
                f"model_reasoning_{iteration}",
                run_type="generation",
                prior_context={"case_id": case_id, "message_count": len(contents)},
                decision={"tool_calls": [call["name"] for call in calls]},
                tool_arguments={"provider": self.settings.provider, "model": self.settings.model},
                tool_result={
                    "finish_reason": candidate.get("finishReason"),
                    "usage": payload.get("usageMetadata", {}),
                },
                started=started,
            )
            contents.append(content)
            if not calls:
                text = "".join(part.get("text", "") for part in content["parts"] if "text" in part)
                try:
                    outcome = AgentOutcome.model_validate_json(text)
                except (ValidationError, ValueError):
                    self.trajectories.record_run(
                        trace_id,
                        "output_validation",
                        run_type="evaluator",
                        prior_context={"case_id": case_id, "model_iteration": iteration},
                        decision={"accepted": False, "retry": True},
                        tool_result={
                            "error": "The model did not return the required JSON object.",
                            "finish_reason": candidate.get("finishReason"),
                        },
                        status="retry",
                    )
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": (
                                        "Return concise valid JSON with every required key "
                                        "and no commentary."
                                    )
                                }
                            ],
                        }
                    )
                    continue
                grounding_errors = self._grounding_errors(
                    outcome, retrieved_ids, grounding_text, review["decision"]
                )
                self.trajectories.record_run(
                    trace_id,
                    "grounding_validation",
                    run_type="evaluator",
                    prior_context={
                        "case_id": case_id,
                        "retrieved_evidence_ids": sorted(retrieved_ids),
                    },
                    decision={"accepted": not grounding_errors},
                    tool_result={
                        "errors": grounding_errors,
                        "cited_evidence_ids": outcome.evidence_ids,
                    },
                    status="success" if not grounding_errors else "retry",
                )
                if grounding_errors:
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": (
                                        "Correct the JSON answer. Grounding validation found: "
                                        f"{'; '.join(grounding_errors)}"
                                    )
                                }
                            ],
                        }
                    )
                    continue
                return {
                    **outcome.model_dump(),
                    "provider": self.settings.provider,
                    "model": self.settings.model,
                    "external_action_taken": False,
                }
            response_parts = []
            for call in calls:
                name = call["name"]
                arguments = call.get("args", {})
                tool_started = time.monotonic()
                result = self._execute_tool(name, arguments, actor_id, trace_id, case_id)
                if name == "search_evidence":
                    retrieved_ids.update(
                        str(item["evidence_id"]) for item in result if item.get("evidence_id")
                    )
                    grounding_text += " " + " ".join(str(item.get("text", "")) for item in result)
                self.trajectories.record_run(
                    trace_id,
                    name,
                    run_type="tool",
                    prior_context={"case_id": case_id, "model_iteration": iteration},
                    decision={"selected_by_model": True},
                    tool_name=name,
                    tool_arguments=arguments,
                    tool_result=result,
                    started=tool_started,
                )
                response_parts.append(
                    {"functionResponse": {"name": name, "response": {"result": result}}}
                )
            contents.append({"role": "user", "parts": response_parts})
        raise RuntimeError("model exceeded the bounded tool-call iteration limit")
