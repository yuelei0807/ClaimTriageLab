"""Deterministic evidence-linked case brief fallback."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from claimtriagelab.evidence.schemas import (
    BriefStatement,
    CaseBrief,
    ExtractedFact,
    PacketExtraction,
)

REQUIRED_BRIEF_FIELDS = {
    "Claim ID",
    "Incident Date",
    "Reported Date",
    "Incident Type",
    "Claim Amount",
}


def _statement(text: str, facts: list[ExtractedFact]) -> BriefStatement:
    if not facts:
        raise ValueError("brief statements require at least one supporting fact")
    return BriefStatement(
        text=text,
        fact_ids=[fact.fact_id for fact in facts],
        evidence_ids=[fact.evidence_id for fact in facts],
        source_links=[fact.locator for fact in facts],
    )


def _currency(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace("$", "").replace(",", ""))
    except InvalidOperation:
        return None


def build_case_brief(extraction: PacketExtraction) -> CaseBrief:
    """Build a cited brief while excluding untrusted instruction text from factual prose."""
    verified = [fact for fact in extraction.facts if fact.quality_flag == "verified"]
    by_field = {fact.field: fact for fact in verified}
    case_id = by_field.get("Claim ID")
    facts = [
        _statement(f"{fact.field}: {fact.value}", [fact])
        for fact in verified
        if fact.field != "Narrative"
    ]
    signals: list[BriefStatement] = []
    conflicts: list[BriefStatement] = []
    amount = _currency(by_field["Claim Amount"].value) if "Claim Amount" in by_field else None
    coverage = (
        _currency(by_field["Coverage Amount"].value) if "Coverage Amount" in by_field else None
    )
    if amount is not None and coverage is not None and amount > coverage:
        conflicts.append(
            _statement(
                "Claim amount exceeds the stated coverage amount.",
                [by_field["Claim Amount"], by_field["Coverage Amount"]],
            )
        )
    if by_field.get("Police Report") and by_field["Police Report"].value == "No":
        signals.append(
            _statement("No police report is listed in the packet.", [by_field["Police Report"]])
        )
    missing = sorted(REQUIRED_BRIEF_FIELDS - set(by_field))
    questions = [f"Can the reviewer obtain or confirm {field}?" for field in missing]
    if conflicts:
        questions.append("Can the reviewer reconcile the claim and coverage amounts?")
    return CaseBrief(
        case_id=case_id.value if case_id else "unknown_case",
        facts=facts,
        signals=signals,
        conflicts=conflicts,
        missing_items=missing,
        suggested_questions=questions,
        warnings=extraction.warnings,
    )


def validate_supported_statement(statement: BriefStatement, extraction: PacketExtraction) -> None:
    """Allow only deterministic statements derived from the referenced fact values."""
    facts = {fact.fact_id: fact for fact in extraction.facts}
    if not set(statement.fact_ids) <= set(facts):
        raise ValueError("statement contains unsupported fact_ids")
    supported_evidence = {facts[fact_id].evidence_id for fact_id in statement.fact_ids}
    supported_links = {facts[fact_id].locator for fact_id in statement.fact_ids}
    if not set(statement.evidence_ids) <= supported_evidence:
        raise ValueError("statement contains unsupported evidence_ids")
    if not set(statement.source_links) <= supported_links:
        raise ValueError("statement contains unsupported source links")
    deterministic = build_case_brief(extraction)
    allowed = deterministic.facts + deterministic.signals + deterministic.conflicts
    if statement not in allowed:
        raise ValueError("statement text is not supported by the deterministic brief rules")


def render_brief_markdown(brief: CaseBrief) -> str:
    """Render a concise reviewer brief with source links beside every factual statement."""
    sections = [f"# Case brief: {brief.case_id}"]
    for title, statements in (
        ("Verified facts", brief.facts),
        ("Signals for review", brief.signals),
        ("Conflicts", brief.conflicts),
    ):
        sections.append(f"\n## {title}")
        for statement in statements:
            links = ", ".join(
                f"[source {index}]({link})"
                for index, link in enumerate(statement.source_links, start=1)
            )
            sections.append(f"- {statement.text} ({links})")
        if not statements:
            sections.append("- None identified.")
    sections.append("\n## Missing items")
    sections.extend(f"- {item}" for item in brief.missing_items or ["None identified."])
    sections.append("\n## Suggested reviewer questions")
    sections.extend(f"- {item}" for item in brief.suggested_questions or ["None."])
    if brief.warnings:
        sections.append("\n## Safety warnings")
        sections.extend(f"- {warning}" for warning in brief.warnings)
    return "\n".join(sections) + "\n"
