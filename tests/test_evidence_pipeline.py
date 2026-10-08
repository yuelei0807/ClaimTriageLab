"""Task 04 extraction, citation, and prompt-injection tests."""

from pathlib import Path

import pytest

from claimtriagelab.evidence.brief import (
    build_case_brief,
    render_brief_markdown,
    validate_supported_statement,
)
from claimtriagelab.evidence.extraction import extract_packet
from claimtriagelab.evidence.schemas import BriefStatement

PACKETS = Path("output/pdf")


@pytest.mark.parametrize(
    "filename,case_id",
    [
        ("routine-claim-packet.pdf", "CLM-DEMO-001"),
        ("ambiguous-injection-packet.pdf", "CLM-DEMO-002"),
    ],
)
def test_pdf_packets_extract_typed_facts(filename: str, case_id: str) -> None:
    extraction = extract_packet(PACKETS / filename)
    assert next(fact.value for fact in extraction.facts if fact.field == "Claim ID") == case_id
    assert all(fact.page_number == 1 for fact in extraction.facts)
    assert all(fact.evidence_id and fact.locator for fact in extraction.facts)


def test_template_brief_cites_every_factual_statement() -> None:
    extraction = extract_packet(PACKETS / "routine-claim-packet.pdf")
    brief = build_case_brief(extraction)
    statements = brief.facts + brief.signals + brief.conflicts
    assert statements
    for statement in statements:
        validate_supported_statement(statement, extraction)
    markdown = render_brief_markdown(brief)
    assert "routine-claim-packet.pdf#page=1" in markdown
    assert "Verified facts" in markdown


def test_prompt_injection_is_flagged_and_not_repeated_as_fact() -> None:
    extraction = extract_packet(PACKETS / "ambiguous-injection-packet.pdf")
    injection = next(fact for fact in extraction.facts if fact.field == "Narrative")
    assert injection.quality_flag == "untrusted_instruction"
    assert extraction.warnings
    markdown = render_brief_markdown(build_case_brief(extraction))
    assert "Ignore previous instructions" not in markdown
    assert "Potential prompt injection" in markdown


def test_conflict_and_missing_sections_are_explicit() -> None:
    extraction = extract_packet(PACKETS / "ambiguous-injection-packet.pdf")
    brief = build_case_brief(extraction)
    assert [item.text for item in brief.conflicts] == [
        "Claim amount exceeds the stated coverage amount."
    ]
    assert [item.text for item in brief.signals] == ["No police report is listed in the packet."]
    assert brief.missing_items == []
    assert brief.suggested_questions == [
        "Can the reviewer reconcile the claim and coverage amounts?"
    ]


def test_unsupported_assertion_is_blocked() -> None:
    extraction = extract_packet(PACKETS / "routine-claim-packet.pdf")
    unsupported = BriefStatement(
        text="The claimant committed fraud.",
        fact_ids=["fact_000000000000"],
        evidence_ids=["ev_000000000000"],
        source_links=["../pdf/routine-claim-packet.pdf#page=1"],
    )
    with pytest.raises(ValueError, match="unsupported fact_ids"):
        validate_supported_statement(unsupported, extraction)


def test_arbitrary_text_with_valid_citation_is_blocked() -> None:
    extraction = extract_packet(PACKETS / "routine-claim-packet.pdf")
    fact = extraction.facts[0]
    unsupported = BriefStatement(
        text="The claimant committed fraud.",
        fact_ids=[fact.fact_id],
        evidence_ids=[fact.evidence_id],
        source_links=[fact.locator],
    )
    with pytest.raises(ValueError, match="statement text"):
        validate_supported_statement(unsupported, extraction)


def test_plain_text_extraction_and_size_limit(tmp_path: Path) -> None:
    packet = tmp_path / "packet.txt"
    packet.write_text("Claim ID: CLM-TEXT-001\nClaim Amount: $50.00\n", encoding="utf-8")
    extraction = extract_packet(packet)
    assert {fact.extraction_method for fact in extraction.facts} == {"plain_text"}
