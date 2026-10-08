"""Export persisted application traces to Langfuse through OTLP/HTTP."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime
from typing import Any

import httpx


def _hex_id(value: str, length: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _nanos(value: str) -> str:
    return str(int(datetime.fromisoformat(value).timestamp() * 1_000_000_000))


def _attr(key: str, value: Any) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return {"key": key, "value": {"stringValue": text}}


class LangfuseExporter:
    """Map the local thread/trace/run hierarchy to Langfuse sessions and spans."""

    def __init__(self, host: str, public_key: str, secret_key: str) -> None:
        self.host = host.rstrip("/")
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "x-langfuse-ingestion-version": "4",
        }

    @classmethod
    def from_environment(cls) -> LangfuseExporter | None:
        host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL", "")
        public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret = os.getenv("LANGFUSE_SECRET_KEY", "")
        return cls(host, public, secret) if host and public and secret else None

    def export(self, trace: dict[str, Any], runs: list[dict[str, Any]]) -> None:
        trace_hex = _hex_id(trace["trace_id"], 32)
        root_span = _hex_id(f"{trace['trace_id']}:root", 16)
        end = trace.get("completed_at") or trace["started_at"]
        root = {
            "traceId": trace_hex,
            "spanId": root_span,
            "name": trace["task_type"],
            "kind": 1,
            "startTimeUnixNano": _nanos(trace["started_at"]),
            "endTimeUnixNano": _nanos(end),
            "attributes": [
                _attr("langfuse.session.id", trace["thread_id"]),
                _attr("langfuse.trace.name", trace["task_type"]),
                _attr("langfuse.trace.input", trace["user_intent"]),
                _attr("langfuse.trace.output", trace["outcome"]),
                _attr("claimtriage.trace_id", trace["trace_id"]),
            ],
            "status": {"code": 2 if trace["status"] in {"error", "failed"} else 1},
        }
        spans = [root]
        for run in runs:
            observation_type = "generation" if run["run_type"] == "generation" else "span"
            attributes = [
                _attr("langfuse.observation.type", observation_type),
                _attr("langfuse.observation.input", run["tool_arguments"] or run["prior_context"]),
                _attr("langfuse.observation.output", run["tool_result"]),
                _attr("claimtriage.run_id", run["run_id"]),
                _attr("claimtriage.run_type", run["run_type"]),
            ]
            spans.append(
                {
                    "traceId": trace_hex,
                    "spanId": _hex_id(run["run_id"], 16),
                    "parentSpanId": root_span,
                    "name": run["step_name"],
                    "kind": 1,
                    "startTimeUnixNano": _nanos(run["started_at"]),
                    "endTimeUnixNano": _nanos(run["completed_at"]),
                    "attributes": attributes,
                    "status": {"code": 1 if run["status"] == "success" else 2},
                }
            )
        body = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [_attr("service.name", "claimtriagelab")]},
                    "scopeSpans": [{"scope": {"name": "claimtriagelab"}, "spans": spans}],
                }
            ]
        }
        response = httpx.post(
            f"{self.host}/api/public/otel/v1/traces",
            headers=self.headers,
            json=body,
            timeout=30,
        )
        response.raise_for_status()
