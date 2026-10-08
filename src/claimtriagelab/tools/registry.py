"""Least-privilege direct-Python tool registry with auditing and retries."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from claimtriagelab.indicators.rules import triage_with_rules
from claimtriagelab.limits import DEFAULT_LIMITS
from claimtriagelab.telemetry import TRACER, set_common_attributes
from claimtriagelab.tools.contracts import (
    CalculateIndicatorsInput,
    ClaimInput,
    EvidenceInput,
    PolicyInput,
    SaveReviewInput,
    ToolContext,
)
from claimtriagelab.tools.store import ToolStore


class ToolError(RuntimeError):
    code = "tool_error"


class UnknownToolError(ToolError):
    code = "unknown_tool"


class UnauthorizedToolError(ToolError):
    code = "unauthorized"


class InvalidToolInputError(ToolError):
    code = "invalid_input"


class ToolNotFoundError(ToolError):
    code = "not_found"


class ToolTimeoutError(ToolError):
    code = "timeout"


@dataclass(frozen=True)
class ToolDefinition:
    input_model: type[BaseModel]
    required_roles: frozenset[str]
    handler: Callable[[BaseModel, ToolContext, float, float, int], ToolRun]


@dataclass(frozen=True)
class ToolRun:
    result: dict[str, Any]
    audit_committed: bool = False


def _safe_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    safe = {
        key: value for key, value in payload.items() if key.endswith("_id") or key in {"decision"}
    }
    if "idempotency_key" in payload:
        safe["idempotency_key_hash"] = hashlib.sha256(
            str(payload["idempotency_key"]).encode()
        ).hexdigest()[:12]
    return safe


class ToolRegistry:
    max_attempts = DEFAULT_LIMITS.tool_retry_budget

    def __init__(self, store: ToolStore) -> None:
        self.store = store
        read_roles = frozenset({"claim_reader", "reviewer"})
        self._definitions = {
            "get_claim": ToolDefinition(ClaimInput, read_roles, self._get_claim),
            "get_policy": ToolDefinition(PolicyInput, read_roles, self._get_policy),
            "get_evidence": ToolDefinition(EvidenceInput, read_roles, self._get_evidence),
            "calculate_indicators": ToolDefinition(
                CalculateIndicatorsInput, read_roles, self._calculate_indicators
            ),
            "save_review": ToolDefinition(
                SaveReviewInput, frozenset({"reviewer"}), self._save_review
            ),
        }

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def execute(
        self, tool_name: str, payload: dict[str, Any], context: ToolContext
    ) -> dict[str, Any]:
        started = time.monotonic()
        span = TRACER.start_span("claimtriagelab.tool.execute")
        set_common_attributes(span, correlation_id=context.correlation_id, operation=tool_name)
        deadline = started + (context.timeout_ms / 1_000)
        attempts = 0
        audit_committed = False
        status = "error"
        error_code: str | None = None
        safe_arguments = _safe_arguments(payload)
        try:
            definition = self._definitions.get(tool_name)
            if definition is None:
                raise UnknownToolError(f"tool is not allowlisted: {tool_name}")
            if not context.roles & definition.required_roles:
                raise UnauthorizedToolError(f"actor cannot execute {tool_name}")
            try:
                validated = definition.input_model.model_validate(payload)
            except ValidationError as error:
                raise InvalidToolInputError("tool input validation failed") from error
            while attempts < self.max_attempts:
                attempts += 1
                try:
                    run = definition.handler(validated, context, started, deadline, attempts)
                    audit_committed = run.audit_committed
                    break
                except sqlite3.OperationalError as error:
                    if "locked" not in str(error).lower() or attempts == self.max_attempts:
                        raise
                    time.sleep(0.01 * attempts)
            elapsed_ms = (time.monotonic() - started) * 1_000
            if not audit_committed and time.monotonic() >= deadline:
                raise ToolTimeoutError(f"tool exceeded {context.timeout_ms} ms")
            status = "success"
            return run.result
        except TimeoutError as error:
            error_code = ToolTimeoutError.code
            status = "rejected"
            raise ToolTimeoutError(f"tool exceeded {context.timeout_ms} ms") from error
        except ToolError as error:
            error_code = error.code
            status = "denied" if error.code in {"unauthorized", "unknown_tool"} else "rejected"
            raise
        finally:
            span.set_attribute("claimtriagelab.status", status)
            span.set_attribute("claimtriagelab.attempt_count", attempts)
            span.set_attribute("claimtriagelab.duration_ms", (time.monotonic() - started) * 1_000)
            if error_code:
                span.set_attribute("claimtriagelab.error_code", error_code)
            if not audit_committed:
                elapsed_ms = (time.monotonic() - started) * 1_000
                self.store.audit(
                    correlation_id=context.correlation_id,
                    actor_id=context.actor_id,
                    tool_name=tool_name,
                    status=status,
                    arguments=safe_arguments,
                    error_code=error_code,
                    duration_ms=elapsed_ms,
                    attempt_count=attempts,
                )
            span.end()

    def _required(self, record: dict[str, Any] | None, kind: str) -> dict[str, Any]:
        if record is None:
            raise ToolNotFoundError(f"{kind} was not found")
        return record

    def _get_claim(
        self, request: BaseModel, _: ToolContext, __: float, ___: float, ____: int
    ) -> ToolRun:
        claim_id = request.claim_id  # type: ignore[attr-defined]
        return ToolRun(
            self._required(self.store.get_record("claims", "claim_id", claim_id), "claim")
        )

    def _get_policy(
        self, request: BaseModel, _: ToolContext, __: float, ___: float, ____: int
    ) -> ToolRun:
        policy_id = request.policy_id  # type: ignore[attr-defined]
        return ToolRun(
            self._required(self.store.get_record("policies", "policy_id", policy_id), "policy")
        )

    def _get_evidence(
        self, request: BaseModel, _: ToolContext, __: float, ___: float, ____: int
    ) -> ToolRun:
        evidence_id = request.evidence_id  # type: ignore[attr-defined]
        return ToolRun(
            self._required(
                self.store.get_record("evidence", "evidence_id", evidence_id), "evidence"
            )
        )

    def _calculate_indicators(
        self, request: BaseModel, _: ToolContext, __: float, ___: float, ____: int
    ) -> ToolRun:
        claim_id = request.claim_id  # type: ignore[attr-defined]
        claim = self._required(self.store.get_record("claims", "claim_id", claim_id), "claim")
        result = triage_with_rules(claim, self.store.evidence_map(claim_id))
        return ToolRun(result.model_dump(mode="json"))

    def _save_review(
        self,
        request: BaseModel,
        context: ToolContext,
        started: float,
        deadline: float,
        attempt_count: int,
    ) -> ToolRun:
        data = request.model_dump()
        if self.store.get_record("claims", "claim_id", data["case_id"]) is None:
            raise ToolNotFoundError("case was not found")
        try:
            review, replayed = self.store.save_review_with_audit(
                case_id=data["case_id"],
                reviewer_id=context.actor_id,
                decision=data["decision"],
                reason=data["reason"],
                idempotency_key=data["idempotency_key"],
                correlation_id=context.correlation_id,
                arguments=_safe_arguments(data),
                deadline_monotonic=deadline,
                started_monotonic=started,
                attempt_count=attempt_count,
            )
        except ValueError as error:
            raise InvalidToolInputError(str(error)) from error
        return ToolRun({"review": review, "idempotent_replay": replayed}, audit_committed=True)
