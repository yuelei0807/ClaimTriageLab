"""Phase-aware evaluation entry point."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    dataset_loaded = Path("data/reports/quality_report.json").is_file()
    metrics_path = Path("artifacts/baseline/metrics.json")
    model_trained = metrics_path.is_file()
    packet_tests_ready = all(
        path.is_file()
        for path in (
            Path("output/pdf/routine-claim-packet.pdf"),
            Path("output/pdf/ambiguous-injection-packet.pdf"),
            Path("output/briefs/routine-claim-brief.md"),
            Path("output/briefs/ambiguous-injection-brief.md"),
        )
    )
    tool_demo_ready = Path("artifacts/tools-demo-audit.json").is_file()
    workflow_demo_ready = Path("artifacts/workflow-demo.json").is_file()
    persistence_demo_ready = Path("artifacts/persistence-demo/report.json").is_file()
    baseline = None
    if model_trained:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        baseline = {
            "version": metrics["logistic"]["version"],
            "threshold_version": metrics["threshold_version"],
            "holdout": metrics["logistic"]["holdout"],
        }
    report = {
        "phase": "task-08-observability-security",
        "status": "ready",
        "dataset_loaded": dataset_loaded,
        "model_trained": model_trained,
        "packet_tests_ready": packet_tests_ready,
        "tool_demo_ready": tool_demo_ready,
        "workflow_demo_ready": workflow_demo_ready,
        "persistence_demo_ready": persistence_demo_ready,
        "baseline": baseline,
        "service_cost_usd": 0,
        "message": (
            "Authenticated review, audit integrity, and sanitized tracing are ready; "
            "real claims remain prohibited."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
