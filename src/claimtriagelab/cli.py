"""Command line interface for local project operations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from claimtriagelab.evidence.brief import build_case_brief, render_brief_markdown
from claimtriagelab.evidence.extraction import extract_packet
from claimtriagelab.health import build_health_report
from claimtriagelab.ingestion.pipeline import SAMPLE_ROWS, run_ingestion
from claimtriagelab.models.baseline import train_and_evaluate
from claimtriagelab.persistence import backup_database, restore_database
from claimtriagelab.workflow.app import ReviewerSecurity, create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimtriagelab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    health = subparsers.add_parser("health", help="run a local health check")
    health.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ingest = subparsers.add_parser("ingest", help="generate and validate the pinned synthetic data")
    ingest.add_argument("--source-dir", type=Path, required=True, help="pinned upstream checkout")
    ingest.add_argument(
        "--output-dir", type=Path, default=Path("data"), help="generated output root"
    )
    ingest.add_argument("--rows", type=int, default=SAMPLE_ROWS, help="number of rows to generate")
    train = subparsers.add_parser("train-baseline", help="train and evaluate Task 03 baselines")
    train.add_argument("--data-dir", type=Path, default=Path("data"))
    train.add_argument("--output-dir", type=Path, default=Path("artifacts/baseline"))
    brief = subparsers.add_parser("build-brief", help="extract a packet and build a cited brief")
    brief.add_argument("--packet", type=Path, required=True)
    brief.add_argument("--output", type=Path, required=True)
    reviewer = subparsers.add_parser("serve-reviewer", help="run the local human-review UI")
    reviewer.add_argument("--database", type=Path, default=Path("artifacts/workflow.sqlite3"))
    reviewer.add_argument("--reviewer-id", default="local_reviewer")
    reviewer.add_argument("--host", default="127.0.0.1")
    reviewer.add_argument("--port", type=int, default=8000)
    backup = subparsers.add_parser("backup-database", help="create a verified SQLite backup")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore-database", help="restore a verified SQLite backup")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--database", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "health":
        report = build_health_report()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"{report.project} {report.version}: {report.status}")
    elif args.command == "ingest":
        report = run_ingestion(args.source_dir, args.output_dir, args.rows)
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.command == "train-baseline":
        report = train_and_evaluate(args.data_dir, args.output_dir)
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.command == "build-brief":
        brief = build_case_brief(extract_packet(args.packet))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_brief_markdown(brief), encoding="utf-8")
        print(json.dumps(brief.model_dump(mode="json"), indent=2, sort_keys=True))
    elif args.command == "serve-reviewer":
        import uvicorn

        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("serve-reviewer is restricted to a loopback host")
        password = os.environ.get("CLAIMTRIAGE_REVIEWER_PASSWORD")
        csrf_secret = os.environ.get("CLAIMTRIAGE_CSRF_SECRET")
        if not password or not csrf_secret:
            raise SystemExit(
                "CLAIMTRIAGE_REVIEWER_PASSWORD and CLAIMTRIAGE_CSRF_SECRET are required"
            )
        uvicorn.run(
            create_app(
                args.database,
                ReviewerSecurity(args.reviewer_id, password, csrf_secret),
            ),
            host=args.host,
            port=args.port,
        )
    elif args.command == "backup-database":
        backup_database(args.database, args.output)
        print(json.dumps({"status": "ok", "backup": str(args.output)}, sort_keys=True))
    elif args.command == "restore-database":
        restore_database(args.backup, args.database)
        print(json.dumps({"status": "ok", "database": str(args.database)}, sort_keys=True))


if __name__ == "__main__":
    main()
