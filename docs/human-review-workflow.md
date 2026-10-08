# Human review workflow

Task 06 implements a LangGraph state machine with SQLite checkpoints. Each case uses the stable thread ID `claim:{case_id}` and advances through intake, evidence lookup, model-driven triage, a compact brief, and `interrupt()` before any review write. Deterministic indicators remain visible as independently reproducible safety signals; Groq or Gemini produces the queue category and priority score from real tool results.

After the human response, the graph resumes into a bounded model tool loop. Qdrant semantic retrieval and allowlisted record reads are recorded as tool runs. A deterministic grounding evaluator rejects unknown citations, missing citations, unsupported information requests, and inconsistent category/score combinations, then asks the model to correct the answer within the same trace.

## Resume boundary

`WorkflowService.resume()` accepts an actor and trusted role set. It rejects callers without `reviewer` before advancing the checkpoint. The review node then calls the allowlisted `save_review` tool, which independently enforces the reviewer role, validates the decision, and atomically commits the idempotent review with its success audit event.

If the process stops while a case is paused, a new service instance opens the same database and reads the pending checkpoint. If execution is replayed after the review side effect, the same idempotency key returns the original review instead of creating a duplicate.

## Local reviewer page

Start the page with:

```bash
uv run claimtriagelab serve-reviewer --database artifacts/workflow-demo.sqlite3
```

Open `/login` to enter the configured reviewer identity, then use the dashboard to select a case. The case workspace presents human-readable signals, linked evidence, workflow progress, governance status, and the three allowed review actions. Idempotency keys are generated internally. Signed session cookies, CSRF validation, and request-size limits protect state-changing actions, and the server remains bound to loopback by default.

Run `make showcase-data` to create four reusable synthetic cases spanning priority, routine, insufficient-information, pending, and completed states.

Completed cases remain reviewable. A follow-up review appends a new decision and audit event while preserving the full earlier review history. Reviewers can also restore the canonical sample state with **Reset demo cases** on the dashboard; the application rebuilds the synthetic database without requiring a process restart.

Run `make workflow-demo` to create a case, pause it, close the first service, restore it with a new service instance, resume it as a reviewer, and write `artifacts/workflow-demo.json` with the checkpoints and audit event.
