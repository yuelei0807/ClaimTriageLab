"""Typed extraction and case-brief contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fact_id: Annotated[str, StringConstraints(pattern=r"^fact_[a-f0-9]{12}$")]
    field: Text
    value: Text
    evidence_id: Annotated[str, StringConstraints(pattern=r"^ev_[a-f0-9]{12}$")]
    source_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    page_number: int = Field(ge=1)
    locator: Text
    extraction_method: Literal["pdf_text", "plain_text"]
    quality_flag: Literal["verified", "untrusted_instruction", "ambiguous"]


class PacketExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: Text
    source_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    facts: list[ExtractedFact]
    warnings: list[Text]

    @model_validator(mode="after")
    def source_hashes_match(self) -> PacketExtraction:
        if any(fact.source_hash != self.source_hash for fact in self.facts):
            raise ValueError("fact source_hash must match packet source_hash")
        return self


class BriefStatement(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: Text
    fact_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    source_links: list[Text] = Field(min_length=1)


class CaseBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: Text
    facts: list[BriefStatement]
    signals: list[BriefStatement]
    conflicts: list[BriefStatement]
    missing_items: list[Text]
    suggested_questions: list[Text]
    warnings: list[Text]
