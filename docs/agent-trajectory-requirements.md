# Agent continuation and trajectory specification

## Production-ready implementation brief

Extend ClaimTriageLab so a human review is an input to the workflow rather than its final
event. After every review, run a bounded, auditable continuation appropriate to the decision.
For `request_information`, inspect only authorized claim, policy, and evidence records; report
what was checked; identify missing or conflicting information; create a cited collection
checklist; and preserve the result for the next reviewer. Never fabricate evidence or treat a
public web search as evidence about a claimant.

Persist execution at three levels:

1. **Thread** — the durable case/session containing all turns and tasks (`thread_id`).
2. **Trace** — one user intent or workflow continuation within a thread (`trace_id`).
3. **Run** — one ordered node, decision, tool call, or evaluator operation (`run_id`, with an
   optional `parent_run_id`). This is equivalent to an OpenTelemetry span at the telemetry
   boundary.

The reviewer UI must provide Run, Trace, and Thread tabs. Run shows the bounded prior context,
decision or tool, redacted arguments, result, status, duration, and evaluation findings for each
step. Trace shows the ordered strategy for a single task and its outcome. Thread shows every
trace across the case lifecycle and highlights failures, warnings, human turns, and possible
context drift. Do not expose hidden chain-of-thought; store concise decision summaries and
observable inputs and outputs.

Use SQLite for zero-cost durable local storage and LangGraph SQLite checkpoints for resumable
workflow state. Use deterministic code evaluators first: required-step order, tool failure,
schema completeness, evidence provenance, state-transition validity, and case/thread consistency.
Store every finding with the trace. Treat automated findings as diagnostic signals rather than
proof that a semantic decision is correct. Keep an adapter path for OpenTelemetry-compatible
open-source viewers such as Phoenix or MLflow, without making either service required.

## Acceptance criteria

- A reviewer decision creates a new trace and at least one observable run.
- `request_information` produces an evidence-gap report and collection checklist automatically.
- Completed cases can accept a later review and run the same continuation behavior.
- Threads, traces, runs, and evaluation findings survive process restart.
- The three UI tabs reconstruct history without rerunning the workflow.
- Every run has stable correlation IDs, ordering, status, timestamps, and JSON-safe context.
- Evaluation catches a failed run, missing required step, and mismatched case context.
- Existing authorization, CSRF, resource limits, idempotency, and append-only audit behavior remain.

