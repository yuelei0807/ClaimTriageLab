"""Start the public demo with a disposable copy of the verified showcase seed."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import uvicorn

from claimtriagelab.workflow.app import ReviewerSecurity, create_app


def required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    database = Path(os.getenv("CLAIMTRIAGE_DATABASE_PATH", "/tmp/claimtriage/showcase.sqlite3"))
    seed = Path(os.getenv("CLAIMTRIAGE_SEED_DATABASE", "deploy/showcase_seed.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True)
    if not database.exists():
        if not seed.exists():
            raise RuntimeError(f"showcase seed database was not found: {seed}")
        shutil.copy2(seed, database)
    security = ReviewerSecurity(
        os.getenv("CLAIMTRIAGE_REVIEWER_ID", "showcase_reviewer"),
        required("CLAIMTRIAGE_REVIEWER_PASSWORD"),
        required("CLAIMTRIAGE_CSRF_SECRET"),
        allow_showcase_reset=False,
    )
    uvicorn.run(
        create_app(database, security),
        host="0.0.0.0",  # noqa: S104 - required inside the hosting container
        port=int(os.getenv("PORT", "10000")),
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
