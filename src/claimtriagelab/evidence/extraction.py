"""Bounded extraction from synthetic PDF and text claim packets."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

from claimtriagelab.evidence.schemas import ExtractedFact, PacketExtraction
from claimtriagelab.limits import DEFAULT_LIMITS

MAX_DOCUMENT_BYTES = DEFAULT_LIMITS.max_document_bytes
FIELD_LABELS = {
    "Claim ID",
    "Policy ID",
    "Incident Date",
    "Reported Date",
    "Incident Type",
    "Claim Amount",
    "Coverage Amount",
    "Police Report",
    "Narrative",
}
INJECTION_PATTERN = re.compile(
    r"ignore (all |any )?(previous|prior) instructions|system prompt|developer message|"
    r"do not cite|mark this claim",
    re.IGNORECASE,
)


def _identifier(prefix: str, source_hash: str, field: str, value: str) -> str:
    digest = hashlib.sha256(f"{source_hash}|{field}|{value}".encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _extract_lines(
    text: str, source_name: str, source_hash: str, page: int, method: str
) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        label, value = (part.strip() for part in line.split(":", 1))
        if label not in FIELD_LABELS or not value:
            continue
        quality = "untrusted_instruction" if INJECTION_PATTERN.search(value) else "verified"
        facts.append(
            ExtractedFact(
                fact_id=_identifier("fact", source_hash, label, value),
                field=label,
                value=value,
                evidence_id=_identifier("ev", source_hash, label, value),
                source_hash=source_hash,
                page_number=page,
                locator=f"../pdf/{source_name}#page={page}",
                extraction_method=method,
                quality_flag=quality,
            )
        )
    return facts


def extract_packet(path: Path) -> PacketExtraction:
    """Extract allowlisted fields without following document instructions."""
    size = path.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} byte limit")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    facts: list[ExtractedFact] = []
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        for page_number, page in enumerate(reader.pages, start=1):
            facts.extend(
                _extract_lines(
                    page.extract_text() or "",
                    path.name,
                    source_hash,
                    page_number,
                    "pdf_text",
                )
            )
    else:
        facts.extend(
            _extract_lines(
                path.read_text(encoding="utf-8"), path.name, source_hash, 1, "plain_text"
            )
        )
    warnings = []
    if any(fact.quality_flag == "untrusted_instruction" for fact in facts):
        warnings.append(
            "Potential prompt injection detected and treated as untrusted document text."
        )
    return PacketExtraction(
        source_name=path.name,
        source_hash=source_hash,
        facts=facts,
        warnings=warnings,
    )
