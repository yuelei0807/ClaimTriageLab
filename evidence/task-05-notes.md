# Task 05 evidence notes

- **Date:** 2026-10-06
- **Task:** Tool execution and optional MCP
- **Expected:** Five typed tools, explicit allowlist, least-privilege access, validation, timeout/retry controls, idempotent writes, and audit events for successful and denied calls.
- **Actual:** The direct Python registry implements all five tools. Tests cover malformed and unknown calls, unauthorized writes, retry attempt counts, read and write execution budgets, evidence-linked calculation, audit redaction, atomic review/audit commits, database audit immutability, and idempotent review replay.

## What changed and why

Added a local SQLite tool store and explicit registry. Read roles cannot save reviews, arbitrary tool names cannot execute, and Pydantic rejects extra or malformed fields. Review writes and success audits commit atomically, deadlines are checked before commit, and database triggers reject audit mutation. Audit records retain operational identifiers and timing without review reasons or raw idempotency keys. Direct calls match the current single-process trust boundary; MCP is deferred until a genuine separate integration exists.

## Verification

```bash
make test
make tools-demo
make verify
```

`artifacts/tools-demo-audit.json` contains a successful `calculate_indicators` event and a denied `save_review` event. The denied call has `attempt_count: 0`, showing authorization was checked before execution.

## Limitations and screenshot evidence

Roles currently come from trusted application context rather than authenticated web sessions. Audit rows are database-immutable but are not yet hash chained or externally anchored. Actual Task 05 process/result screenshots remain open because reliable application-window capture is unavailable.
