"""Typed tool inputs and caller authorization context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClaimInput(ToolInput):
    claim_id: Identifier


class PolicyInput(ToolInput):
    policy_id: Identifier


class EvidenceInput(ToolInput):
    evidence_id: Identifier


class CalculateIndicatorsInput(ToolInput):
    claim_id: Identifier


class SaveReviewInput(ToolInput):
    case_id: Identifier
    decision: Literal["approve_referral", "reject_referral", "request_information"]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    idempotency_key: Annotated[
        str, StringConstraints(min_length=12, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ]


@dataclass(frozen=True)
class ToolContext:
    actor_id: str
    roles: frozenset[str]
    correlation_id: str
    timeout_ms: int = 1_000

    def __post_init__(self) -> None:
        if not 10 <= self.timeout_ms <= 5_000:
            raise ValueError("timeout_ms must be between 10 and 5000")
