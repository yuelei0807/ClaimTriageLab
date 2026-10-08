"""Task 08 audit-integrity and sanitized telemetry tests."""

from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from claimtriagelab.tools.contracts import ToolContext
from claimtriagelab.tools.registry import ToolRegistry
from claimtriagelab.tools.store import ToolStore


def seeded_registry(tmp_path: Path) -> tuple[ToolRegistry, ToolStore]:
    store = ToolStore(tmp_path / "security.sqlite3")
    store.seed_case(
        {"claim_id": "claim_sec", "policy_id": "policy_sec"},
        {"policy_id": "policy_sec"},
        [],
    )
    return ToolRegistry(store), store


def test_audit_hash_chain_detects_database_tampering(tmp_path: Path) -> None:
    registry, store = seeded_registry(tmp_path)
    registry.execute(
        "get_claim",
        {"claim_id": "claim_sec"},
        ToolContext("reader_sec", frozenset({"claim_reader"}), "corr_sec"),
    )
    assert store.verify_audit_integrity() is True
    with store.connect() as connection:
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("UPDATE audit_events SET arguments_json = '{}' WHERE sequence = 1")
    with pytest.raises(ValueError, match="audit integrity verification failed"):
        store.verify_audit_integrity()


def test_tool_span_contains_operational_metadata_without_payload(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    registry, _ = seeded_registry(tmp_path)
    registry.execute(
        "get_claim",
        {"claim_id": "claim_sec"},
        ToolContext("reader_sec", frozenset({"claim_reader"}), "corr_trace"),
    )
    spans = exporter.get_finished_spans()
    tool_span = next(span for span in spans if span.name == "claimtriagelab.tool.execute")
    assert tool_span.attributes["claimtriagelab.correlation_id"] == "corr_trace"
    assert tool_span.attributes["claimtriagelab.operation"] == "get_claim"
    assert tool_span.attributes["claimtriagelab.status"] == "success"
    serialized = str(tool_span.attributes)
    assert "payload_json" not in serialized
    assert "reason" not in serialized
