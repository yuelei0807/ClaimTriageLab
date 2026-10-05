# Task 00 evidence notes

- **Date:** 2026-10-05
- **Task:** Project scaffold and reproducibility
- **Expected:** Initialize a Git/Python project with a lockfile, documented local commands, health check, lint, tests, and evaluation entry point.
- **Actual:** Repository initialized on branch `main`; `uv.lock` resolved eight packages; lint and format checks passed; two health tests passed; evaluation readiness returned `ready`; health returned `ok`, `synthetic_only`, and `$0` service cost.

## What changed

Created the source package, command-line health check, test suite, phase-aware evaluation entry point, dependency lock, local quality commands, architecture documentation, data/model/threat placeholders, and ADR-001. Data and artifact directories are ignored except for placeholders. Secrets and local runtime files are excluded through `.gitignore`.

## Why this implementation

The first phase proves that the repository is reproducible before adding data, models, or a web service. The health check has no runtime dependency or network call, so it provides a reliable zero-cost baseline. Ruff and pytest are development-only dependencies pinned in the lockfile.

## Verification command

```bash
PATH="$PWD/.bootstrap/bin:$PATH" UV_CACHE_DIR="$PWD/.bootstrap/uv-cache" make verify
```

The local `.bootstrap` environment was used only because `uv` was not preinstalled and the execution environment could not write to the default cache. It is ignored by Git. A normal developer installation can run `uv sync --dev && make verify` directly.

## Evidence files

- `task-00-process.png`: rendered project scaffold and lock/setup evidence
- `task-00-result.png`: rendered output of the successful verification run
- The matching HTML files preserve selectable text and explain that the images are rendered verification reports.

## Limitations

No dataset, triage logic, web interface, persistent database, or model exists in Task 00. The evaluation script correctly reports those components as absent. The evidence images are rendered from actual command output because native screen capture was unavailable to the execution environment.

