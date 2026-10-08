# Tool execution and authorization

Task 05 exposes five direct Python tools through an explicit registry: `get_claim`, `get_policy`, `get_evidence`, `calculate_indicators`, and `save_review`. Tool discovery never expands authority. Unknown names are denied and audited.

## Access model

| Tool | Allowed roles | Side effect |
|---|---|---|
| `get_claim` | `claim_reader`, `reviewer` | None |
| `get_policy` | `claim_reader`, `reviewer` | None |
| `get_evidence` | `claim_reader`, `reviewer` | None |
| `calculate_indicators` | `claim_reader`, `reviewer` | None |
| `save_review` | `reviewer` | Stores one review decision |

Each call validates a strict Pydantic input contract before execution. Review writes require a 12-128 character idempotency key; replay returns the original review ID without duplicating the decision. The review and its success audit event commit in one SQLite transaction. The write checks its deadline before mutation and immediately before commit, so a timed-out review is rolled back. SQLite uses WAL, foreign keys, a busy timeout, and up to three attempts for transient lock errors. Every call has a 10-5,000 ms execution budget.

Every successful, malformed, missing, unknown, timed-out, or unauthorized call creates an append-only audit row with correlation ID, actor ID, tool name, status, sanitized identifiers, error code, duration, and attempt count. Database triggers reject audit updates and deletes. Reasons and raw idempotency keys are not logged; the latter is represented by a short SHA-256 digest.

## Direct calls versus MCP

The current modular monolith uses direct Python calls because the tools share one local SQLite authority boundary. Adding an MCP process would increase process, authentication, and deployment complexity without providing isolation from a genuinely separate system. If a later integration needs an independent process, only the three read-only retrieval tools should be considered for MCP exposure; `save_review` should remain behind the application authorization boundary.

Run `make tools-demo` to produce `artifacts/tools-demo-audit.json` with one successful indicator call and one denied review write. The demo database and audit report are ignored local artifacts.
