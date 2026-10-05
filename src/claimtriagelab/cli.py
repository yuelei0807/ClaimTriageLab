"""Command line interface for local project operations."""

from __future__ import annotations

import argparse
import json

from claimtriagelab.health import build_health_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimtriagelab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    health = subparsers.add_parser("health", help="run a local health check")
    health.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "health":
        report = build_health_report()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"{report.project} {report.version}: {report.status}")


if __name__ == "__main__":
    main()
