"""Create a reusable synthetic showcase database with varied workflow states."""

from __future__ import annotations

import argparse
from pathlib import Path

from claimtriagelab.showcase import prepare_showcase_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("artifacts/showcase.sqlite3"))
    args = parser.parse_args()
    prepare_showcase_database(args.database)
    print(f"showcase database ready: {args.database}")


if __name__ == "__main__":
    main()
