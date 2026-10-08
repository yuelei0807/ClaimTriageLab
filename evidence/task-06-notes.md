# Task 06 evidence notes

- **Date:** 2026-10-06
- **Task:** Human review and durable workflow
- **Expected:** LangGraph intake-to-review route, SQLite checkpoints, durable interrupt, authorized resume, idempotent post-approval side effect, local reviewer actions, and audit persistence.
- **Actual:** The workflow pauses with a stable case thread, survives service reconstruction, rejects a non-reviewer, resumes through the Task 05 write boundary, and exposes the three review actions on a local FastAPI page.

## Verification

```bash
make test
make workflow-demo
make verify
```

The automated suite reconstructs the workflow service against the same database before resume and verifies the completed checkpoint and persisted success audit. `artifacts/workflow-demo.json` records the same sequence for manual inspection.

## Limitations and screenshot evidence

The page uses a configured local reviewer identity and binds to loopback by default. Authenticated sessions, CSRF protection, and request-size limits remain Task 08 release gates. Actual Task 06 paused/resumed page screenshots have not yet been captured.
