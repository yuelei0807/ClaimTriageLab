"""Protocol tests for free-tier Qdrant and Langfuse integrations."""

from pathlib import Path

from claimtriagelab.langfuse_export import LangfuseExporter
from claimtriagelab.retrieval.qdrant import QdrantEvidenceIndex
from claimtriagelab.trajectory import TrajectoryStore


class Response:
    def __init__(self, payload: dict | None = None, status_code: int = 200) -> None:
        self.payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self) -> dict:
        return self.payload


def test_qdrant_indexes_and_filters_active_case(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    def request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs.get("json", {})))
        if url.endswith("/points/query"):
            return Response(
                {"result": {"points": [{"score": 0.8, "payload": {"evidence_id": "ev_1"}}]}}
            )
        return Response()

    monkeypatch.setattr(
        "claimtriagelab.retrieval.qdrant.httpx.get", lambda u, **k: request("GET", u, **k)
    )
    monkeypatch.setattr(
        "claimtriagelab.retrieval.qdrant.httpx.put", lambda u, **k: request("PUT", u, **k)
    )
    monkeypatch.setattr(
        "claimtriagelab.retrieval.qdrant.httpx.post", lambda u, **k: request("POST", u, **k)
    )
    index = QdrantEvidenceIndex("https://qdrant.example", "secret", "evidence")
    index.index_case("claim_1", [{"evidence_id": "ev_1", "field_name": "report", "value": "yes"}])
    result = index.search("claim_1", "incident report")

    query = next(body for method, url, body in calls if method == "POST" and url.endswith("query"))
    assert query["filter"]["must"][0]["match"]["value"] == "claim_1"
    assert query["query"]["model"] == "sentence-transformers/all-minilm-l6-v2"
    assert result[0]["evidence_id"] == "ev_1"


def test_langfuse_export_preserves_thread_trace_and_run_ids(monkeypatch, tmp_path: Path) -> None:
    trajectories = TrajectoryStore(tmp_path / "trace.sqlite3")
    trace_id = trajectories.start_trace("claim:one", "one", "review_continuation", "review")
    run_id = trajectories.record_run(trace_id, "search_evidence", run_type="tool")
    with trajectories.connect() as connection:
        connection.execute(
            "UPDATE agent_traces SET status='complete', completed_at=started_at WHERE trace_id=?",
            (trace_id,),
        )
    captured = {}
    monkeypatch.setattr(
        "claimtriagelab.langfuse_export.httpx.post",
        lambda *args, **kwargs: captured.update(kwargs) or Response(),
    )
    trace = trajectories.get_trace(trace_id)
    assert trace is not None
    LangfuseExporter("https://langfuse.example", "public", "secret").export(
        trace, trajectories.runs_for_trace(trace_id)
    )

    spans = captured["json"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    attributes = [item for span in spans for item in span["attributes"]]
    values = {item["value"]["stringValue"] for item in attributes}
    assert {"claim:one", trace_id, run_id} <= values
