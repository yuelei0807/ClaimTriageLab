# ClaimTriageLab — zero-cost implementation plan

**Version:** 1.0 · **Date:** 2026-10-05 · **Scope:** US auto property-and-casualty claims · **Mode:** synthetic-data research/demo

## 1. Objective and boundaries

Build an investigator-assist system that prioritizes auto claims for **human review** and produces an evidence-linked case brief. Its output is `routine_review`, `priority_review`, or `insufficient_information`, plus reasons and source references. A score or referral is not a finding of fraud. The software must never deny a claim, accuse a person, contact a claimant, or initiate an investigation without an authorized human decision. The demo contains only synthetic data.

The engineering target is a reproducible, secure, testable workflow using modern open-source components. **Zero monetary cost means local development and local hosting on the existing Mac, with no paid APIs or cloud account required.** Electricity, internet, and existing hardware are outside the software budget. A public, continuously available, production-grade service cannot be promised at zero cost. Public free tiers are optional showcase channels only; they may sleep, expire, change terms, or require billing.

### Success criteria

- A single synthetic claim can be ingested, validated, scored, and shown in a reviewer UI with cited evidence and an audit record.
- Every referral can be reproduced from a pinned dataset version, code commit, ruleset/model version, and threshold.
- A reviewer can approve, reject, or request more information; a paused workflow survives process restart.
- No decision affecting a claimant is automated. Unknown, missing, or conflicting inputs route to human review.
- Automated tests cover data contracts, forbidden tool actions, restart/resume, source citations, and core evaluation metrics.
- Every implementation task has **two real screenshots** (process and result) and an explanatory evidence note. Screenshots are captured as each task is completed, not manufactured in advance.

## 2. Cost and technology decisions

| Component | Chosen zero-cost implementation | Why / limit |
|---|---|---|
| Language and environment | Python 3.12, `uv`, Git, `ruff`, `pytest` | Open-source, reproducible dependency lock and quality gates. |
| API and reviewer UI | FastAPI plus server-rendered Jinja templates | One local service, minimal infrastructure; API contract via OpenAPI. |
| Input contracts | Pydantic v2 | Typed request/response and explicit validation errors. |
| Structured baseline | Rules plus scikit-learn HistGradientBoosting or logistic regression; choose by held-out metrics | The baseline must be interpretable and measured before an AI agent is added. |
| Optional local text model | Ollama or llama.cpp with a verified open-weight, commercially usable model that fits the Mac | Only for bounded extraction and brief drafting. Record exact model card/license and local resource use before installation. Deterministic fallback keeps the project working without it. |
| Optional Jev-like model | Independent OpenJev **small encoder backend** (Laya or Verdict) behind a `DecisionProvider` interface | Compare against baseline on the same cases. OpenJev DiffusionGemma/MLX needs substantial memory and is not a required dependency. TypeSafe Jev is hosted/paid and is excluded. |
| Workflow | Plain Python services initially; LangGraph only for the stateful review and resume flow | Avoid an agent loop where fixed steps suffice. |
| Persistence | SQLite with WAL for claims, features, evidence metadata, review actions, audit events, and LangGraph checkpointing | Durable on local Mac; back up database. Never depend on a free host's ephemeral disk. |
| Retrieval | SQLite FTS5 for policy text and synthetic case notes | A vector database is unnecessary until benchmarked retrieval requires one. If needed, run Qdrant locally; no Pinecone account. |
| Tool interfaces | Local typed Python functions; optional MCP server for a genuine separate integration | A small allowlist is easier to audit. MCP discovery must not confer authority. |
| Telemetry | OpenTelemetry spans to local JSON/SQLite, with redaction | Zero-account baseline. Langfuse Cloud is an optional synthetic-only demo; self-hosted Langfuse has much larger infrastructure needs. |
| Deployment | Local FastAPI bound to `127.0.0.1`; reproducible Dockerfile as an artifact | Local hosting has no subscription. A public free Space/Render deployment is optional, synthetic only, and not an operational guarantee. |

Use `pyproject.toml` and `uv.lock`; pin the model revision and dataset commit/hash. Add `.env.example`, `.gitignore`, `Makefile`, `LICENSE`, `README.md`, `DATA_PROVENANCE.md`, `MODEL_CARD.md`, and `THREAT_MODEL.md`. Do not commit actual secrets, raw claim data, database files, or model weights.

## 3. Dataset decision and validation limits

**Primary public dataset:** [Insurance Claim Fraud Detection Dataset Generator & Framework](https://github.com/MobeenFatimaa/Insurance-Claim-Fraud-Detection-Dataset-Generator). Its repository states an Apache-2.0 license, includes a reproducible synthetic generator, a data dictionary, approximately 100,000 records and 62 columns. Pin a repository commit and independently verify `LICENSE` and the dataset file's terms before redistribution. Start with a stratified 10,000-row development extract to keep the laptop workflow light; retain a frozen holdout from the full set.

**Why this dataset:** It is publicly accessible, auto-claim oriented, broad enough to exercise intake, indicators, scoring, and reviewer workflow, and has a reproducible generator. A 100-million-row alternative is unnecessary for this goal and carries a CC BY-NC license, limiting commercial reuse.

**Critical limitation:** the dataset's fraud label is created by its generator's weighted indicators. It is not independently confirmed fraud. A model can learn the generator rather than discover useful real-world signal. Before training, build a leakage inventory. Exclude the target label, generated risk score, direct rule flags and downstream outcomes from predictive features when they reveal the answer. Document feature availability **at claim-intake time**. Use a chronological split if dates support it; otherwise group related parties/policies and use a frozen holdout. Report the generator's approximate fraud prevalence rather than presenting it as real-world prevalence. Do not report synthetic metrics as real-world fraud detection performance.

**Supplementary evaluation set:** author 50–100 synthetic case packets *after* freezing the model design. Include legitimate unusual claims, missing documents, contradictory statements, repeated parties, ambiguous cases, and counterexamples to each indicator. Two people should independently label at least a subset if collaborators are available; disagreements are documented. This tests the complete evidence and review workflow more honestly than the generator label alone.

**No external live lookups** of personal identity, police records, social media, or claimant data are in scope. No real claim data is sent to inference or telemetry providers.

## 4. Data and decision contracts

`Claim`: claim_id, policy_id, claimant_id (synthetic), incident_at, reported_at, incident_type, amount, location_region, narrative, document_ids, intake_version.

`Evidence`: evidence_id, claim_id, source_type, source_hash, captured_at, extracted_fact, page_or_field_locator, extraction_method, quality_flag. Keep original source separately from extracted facts.

`Indicator`: indicator_id, value, derivation, evidence_ids, rule_version, confidence/quality flag. Indicator presence is not proof of fraud.

`TriageResult`: category, score (if calibrated), threshold_version, indicators, missing_data, contradictory_data, evidence_ids, model_version, generated_at. A brief must distinguish verified facts, inferred signals, and unknowns.

`ReviewDecision`: case_id, reviewer_id, decision (`approve_referral`, `reject_referral`, `request_information`), reason, timestamp. Store immutable audit events for every state transition and tool call. Use pseudonymous IDs throughout the demo.

## 5. Implementation tasks and screenshot evidence

For **every** task below, save `evidence/task-XX-process.png`, `evidence/task-XX-result.png`, and `evidence/task-XX-notes.md`. The process screenshot should show the meaningful implementation or command. The result screenshot should show a passing check or working UI. In notes, record **what changed, why, command/run ID, expected versus actual result, limitations, and source/code version**. Crop out personal information, API keys, local usernames, and private paths if sharing publicly. Screenshots supplement machine-readable logs; do not substitute for tests. Never stage a fake screenshot.

### Task 00 — Project scaffold and reproducibility

Create the repository under `ClaimTriageLab`, initialize Git, Python project, lockfile, source/tests/docs/evidence folders, and CI-like local commands (`make lint`, `make test`, `make eval`). Add architecture decision record ADR-001 explaining local-first zero cost. **Done when:** a clean clone can run the health check and tests using documented commands. **Capture:** project tree and lockfile; successful setup/health check.

### Task 01 — Governance, threat model, and state schema

Write decision policy, forbidden actions, human-review requirements, data retention, trust boundaries, and Pydantic contracts above. Define the LangGraph state narrowly: `case_id`, `stage`, `evidence_ids`, `indicator_ids`, `triage_result_id`, `pending_review_id`, `errors`, `version`; keep large documents in storage rather than graph messages. **Done when:** schema examples validate; invalid/missing fields fail predictably; threat-model review is recorded. **Capture:** schema/diagram; passing contract tests and invalid request response.

### Task 02 — Dataset ingestion and quality report

Pin and download the selected public source, record checksum/license, generate or import a 10k sample, validate schema and distributions, detect duplicates/missingness/date anomalies, and make a leakage inventory with `available_at_intake` for every feature. Store raw, normalized, and holdout data separately. **Done when:** ingestion is reproducible and the quality report includes class balance, splits, feature exclusions, and limitations. **Capture:** ingestion command/code; quality report and row counts.

### Task 03 — Baseline triage engine

Implement transparent indicators and a deterministic triage route first. Train logistic regression and/or gradient boosting on leakage-safe features as challengers. Use a threshold chosen on validation data against a stated investigator review capacity; freeze it before holdout evaluation. Include a fallback route for missing/conflicting data. **Done when:** every output includes rule/model version and evidence IDs; the baseline has a confusion matrix, precision-recall curve, recall at top-k review capacity, calibration, and per-slice error report. **Capture:** threshold/model configuration; reproducible metrics dashboard or report.

### Task 04 — Evidence extraction and case brief

Make a small library of synthetic PDF/text claim packets. Extract text with open-source parsers and normalize facts through typed schemas. Use an optional local LLM only for bounded extraction/summary; validate fields and require a source locator for each factual statement. Fall back to template-generated briefs if no local model is available. Test prompt injection in documents and unsupported assertions. **Done when:** the brief separates facts, signals, conflicts, missing items, and suggested questions; uncited facts are blocked. **Capture:** extraction pipeline; reviewer brief with clickable source references.

### Task 05 — Tool execution and optional MCP

Implement `get_claim`, `get_policy`, `get_evidence`, `calculate_indicators`, and `save_review` as typed functions with least-privilege access. Validate inputs, timeouts, retries, idempotency keys, and audit events. If an independent tool process is useful, expose only read-only functions through a local MCP server and explicitly allowlist its names; compare this against direct Python calls. **Done when:** malformed/unauthorized calls are rejected by code and recorded, without relying on model self-correction. **Capture:** tool registry/contract; successful call and denied call logs.

### Task 06 — Human review and durable workflow

Use LangGraph for the actual stateful route: intake → evidence → triage → brief → `interrupt()` for reviewer → approved/rejected/information requested. Persist checkpoints in SQLite with a stable case/thread ID. Keep side effects after the approval boundary and use idempotency keys because resume may rerun a node. Expose local reviewer UI actions; no terminal-only approval in the finished app. **Done when:** a pending case survives service restart, only an authorized reviewer resumes it, and every decision appears in the audit trail. **Capture:** graph/review page while paused; resumed case after restart with audit entries.

### Task 07 — Context and persistence controls

Keep structured facts and evidence references as source of truth. Set max document size, retrieval count, token budget, workflow steps, and retry budget. Summarize only old narrative context when necessary; retain original evidence and record summary provenance. Back up and restore SQLite. **Done when:** a long synthetic case completes inside limits and can be replayed after a restart/restore. **Capture:** limit configuration and checkpoint records; replay/restore proof.

### Task 08 — Observability and security

Instrument each stage and tool with OpenTelemetry: correlation ID, latency, status, retries, version, token counts if available, and sanitized tool names/arguments. Do not record chain-of-thought, full sensitive documents, or secrets. Add basic auth for local reviewer actions, CSRF protection for forms, request size limits, dependency scans, and audit log integrity checks. Langfuse may be connected to **synthetic** runs to inspect trace/session views, but is not necessary for zero cost. **Done when:** one case can be traced end-to-end and deliberate failures are visible without leaking sensitive fields. **Capture:** instrumentation configuration; redacted trace and security test results.

### Task 09 — Evaluation and release gate

Run frozen holdout evaluation and synthetic case-packet tests. Report precision, recall, PR-AUC, referral yield at a fixed review budget, calibration/Brier score, false referrals, missed referrals, group/slice disparities where meaningful, latency, restart recovery, citation accuracy, and cost (`$0` service charges). Include confidence intervals where sample size supports them. LLM-as-judge can assess brief readability but never define the principal pass/fail. Compare rules, classical ML, optional local LLM, and optional OpenJev using identical inputs and human-labeled cases. **Done when:** evaluation report states both results and limitations; a release checklist has explicit pass/fail gates. **Capture:** evaluation command and dataset version; metrics report and signed-off checklist.

### Task 10 — Local deployment and optional public demo

Package FastAPI and UI with a reproducible Dockerfile, but allow native Mac startup when Docker is unavailable. Bind locally by default; test health, intake, reviewer flow, restart, and backup. Publish a public demo only if desired and only with synthetic cases, no durable approval promises, and no live insurer data. A free Space/Render instance is a showcase, not a production host. **Done when:** setup instructions work on a clean environment and a complete sample case can be replayed. **Capture:** startup/container build; finished reviewer UI and API response.

## 6. Release gates and professional operating rules

1. **Data gate:** dataset license, provenance, split, and leakage review documented.
2. **Decision gate:** no automatic adverse claim decision; every referral reason cites evidence; uncertainty leads to human review.
3. **Quality gate:** tests, lint, frozen evaluation, prompt-injection tests, and restart tests pass.
4. **Security gate:** access controls, redaction, secret scanning, and backup/restore verified.
5. **Cost gate:** no billing account, paid key, metered production dependency, or paid deployment in the required path. Record disk/memory/time usage on the Mac.
6. **Evidence gate:** each task has actual process/result screenshots and a dated explanation of what was done and why.

Any later use with actual insurer claims requires a separate data agreement, privacy/security review, insurer-specific labels and workflow, independent validation, regulator/jurisdiction review, monitoring plan, and operational infrastructure. The synthetic demo is not evidence of real-world detection quality.

## 7. Repository layout

```text
ClaimTriageLab/
  README.md  pyproject.toml  uv.lock  Makefile  Dockerfile  .env.example
  docs/
    implementation-plan.md  architecture.md  DATA_PROVENANCE.md
    MODEL_CARD.md  THREAT_MODEL.md  evaluation-plan.md  adr/
  src/claimtriagelab/
    api/  domain/  ingestion/  indicators/  models/  evidence/
    workflow/  tools/  telemetry/  ui/
  tests/  evals/  scripts/
  evidence/
    task-00-process.png  task-00-result.png  task-00-notes.md
    ...
  data/                 # ignored generated/downloaded data
  artifacts/            # ignored models, local traces, database backups
```

## 8. References verified 2026-10-05

- Dataset source/license and warning: https://github.com/MobeenFatimaa/Insurance-Claim-Fraud-Detection-Dataset-Generator
- Noncommercial large synthetic alternative: https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M
- TypeSafe model pricing and open adapter: https://docs.typesafe.ai/models and https://github.com/typesafe-ai/system-one-adapter-python
- Independent OpenJev and hardware notes: https://github.com/razorback16/openjev
- LangGraph interrupts/persistence: https://langchain-ai.github.io/langgraph/how-tos/create-react-agent-hitl/
- Langfuse free tier and self-hosting resources: https://langfuse.com/pricing and https://langfuse.com/self-hosting
- Render free-tier limitations: https://render.com/docs/free
- Hugging Face Spaces free-host limitations: https://huggingface.co/docs/hub/spaces-overview
- NAIC AI governance and human oversight: https://content.naic.org/insurance-topics/artificial-intelligence

**Plan status:** complete and ready for implementation. Screenshots and test results in Task 00–10 are future evidence requirements; none are claimed as completed implementation.
