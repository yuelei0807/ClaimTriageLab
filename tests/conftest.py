"""Test-only configuration; production has no deterministic agent fallback."""

from __future__ import annotations

import os

os.environ["CLAIMTRIAGE_TEST_MODE"] = "1"
