# Task 01 evidence notes

- **Date:** 2026-10-05
- **Task:** Governance, threat model, and state schema
- **Source version:** working tree after commit `4f9d9f6` (Task 00 scaffold)
- **Expected:** Typed examples validate; malformed and missing fields fail; human-review policy and trust boundaries are documented.
- **Actual:** `make verify` passed with 12 tests. Pydantic contracts cover claim, evidence, indicator, triage result, review decision, and narrow workflow state. Invalid inputs fail with validation errors. The threat review is recorded in `docs/THREAT_MODEL.md`.

## What changed and why

Added strict Pydantic v2 contracts, cross-field checks for dates, evidence citations, uncertainty routing, and paused-state references; documented human authority, forbidden actions, synthetic-only retention, and untrusted-data boundaries. These prevent malformed or unsupported outputs from becoming valid workflow state before dataset ingestion and API work begin.

## Verification

```bash
PATH="$PWD/.bootstrap/bin:$PATH" UV_CACHE_DIR="$PWD/.bootstrap/uv-cache" make verify
```

Result: lint and format passed; `12 passed`; evaluation readiness and health returned `ready` and `ok`. Pydantic and related dependencies are pinned in `uv.lock`.

## Limitations and screenshot evidence

The API, authorization, persistent audit, and evidence ownership checks are future tasks. Task 01 has no HTTP endpoint yet, so invalid input was verified through Pydantic tests rather than an HTTP response. Actual `task-01-process.png` and `task-01-result.png` screenshots have not been captured; this evidence gate remains open. No images were manufactured from text output.
