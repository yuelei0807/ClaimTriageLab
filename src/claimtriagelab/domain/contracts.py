"""Contracts for synthetic intake, evidence, triage, and human review."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
Version = Annotated[str, StringConstraints(min_length=1, max_length=80)]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


class Claim(StrictContract):
    claim_id: Identifier
    policy_id: Identifier
    claimant_id: Identifier
    incident_at: datetime
    reported_at: datetime
    incident_type: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    location_region: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    narrative: Annotated[str, StringConstraints(max_length=20000)]
    document_ids: list[Identifier]
    intake_version: Version

    @model_validator(mode="after")
    def validate_dates_and_documents(self) -> Claim:
        if self.incident_at.tzinfo is None or self.reported_at.tzinfo is None:
            raise ValueError("incident_at and reported_at must include timezone offsets")
        if self.reported_at < self.incident_at:
            raise ValueError("reported_at must be on or after incident_at")
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document_ids must be unique")
        return self


class Evidence(StrictContract):
    evidence_id: Identifier
    claim_id: Identifier
    source_type: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    source_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    captured_at: datetime
    extracted_fact: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    page_or_field_locator: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    extraction_method: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    quality_flag: Literal["verified", "unverified", "conflicting"]


class Indicator(StrictContract):
    indicator_id: Identifier
    value: bool | float | str
    derivation: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    evidence_ids: list[Identifier] = Field(min_length=1)
    rule_version: Version
    quality_flag: Literal["verified", "uncertain", "conflicting"]


class TriageCategory(StrEnum):
    ROUTINE_REVIEW = "routine_review"
    PRIORITY_REVIEW = "priority_review"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class TriageResult(StrictContract):
    category: TriageCategory
    score: float | None = Field(default=None, ge=0, le=1)
    threshold_version: Version
    indicators: list[Indicator]
    missing_data: list[str]
    contradictory_data: list[str]
    evidence_ids: list[Identifier]
    model_version: Version
    generated_at: datetime

    @model_validator(mode="after")
    def validate_evidence_links(self) -> TriageResult:
        cited = set(self.evidence_ids)
        if any(not set(indicator.evidence_ids) <= cited for indicator in self.indicators):
            raise ValueError("indicator evidence_ids must appear in result evidence_ids")
        if (
            self.missing_data or self.contradictory_data
        ) and self.category != TriageCategory.INSUFFICIENT_INFORMATION:
            raise ValueError("missing or contradictory data requires insufficient_information")
        return self


class ReviewAction(StrEnum):
    APPROVE_REFERRAL = "approve_referral"
    REJECT_REFERRAL = "reject_referral"
    REQUEST_INFORMATION = "request_information"


class ReviewDecision(StrictContract):
    case_id: Identifier
    reviewer_id: Identifier
    decision: ReviewAction
    reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    timestamp: datetime


class WorkflowState(StrictContract):
    case_id: Identifier
    stage: Literal["intake", "evidence", "triage", "brief", "pending_review", "complete"]
    evidence_ids: list[Identifier]
    indicator_ids: list[Identifier]
    triage_result_id: Identifier | None
    pending_review_id: Identifier | None
    errors: list[str]
    version: Version

    @model_validator(mode="after")
    def validate_pending_review(self) -> WorkflowState:
        if (self.stage == "pending_review") != (self.pending_review_id is not None):
            raise ValueError("pending_review_id is required only at pending_review stage")
        return self
