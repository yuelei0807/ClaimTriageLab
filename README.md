# ClaimTriageLab

ClaimTriageLab is a free-tier, local-first research project for prioritizing synthetic auto-insurance claims for human review. It produces review recommendations and evidence references. It does not determine fraud, deny claims, or take action against a claimant.

## Implementation status

Tasks 00–09 establish governance, synthetic data, measured baselines, cited evidence, durable review, bounded context, verified recovery, authenticated reviewer actions and webhook access, LLM-as-a-judge evaluation, Docker packaging, CSRF and body-size enforcement, sanitized OpenTelemetry spans, hash-chained audits, secret scanning, and dependency auditing. The current agent uses LangGraph, Groq or Gemini function calling, Qdrant semantic evidence retrieval, grounded-output validation, and Langfuse trace export.

## Requirements

- macOS or Linux
- Python 3.12+
- `uv` 0.8+
- Git and Make

## Setup

```bash
uv sync --dev
make verify
```

Run the health check directly:

```bash
uv run claimtriagelab health --json
```

Expected result: JSON with `status: "ok"`, the project name, Python version, and `service_cost_usd: 0`.

## Local quality commands

```bash
make lint    # static checks and formatting verification
make test    # unit tests
make eval    # phase-aware evaluation readiness report
make verify  # all three gates plus health check
make baseline # train and evaluate Task 03 baselines after ingestion
make briefs   # reproduce Task 04 PDF packets and cited briefs
make tools-demo # run successful and denied Task 05 calls with audit output
make workflow-demo # prove Task 06 pause, restart, resume, and audit persistence
make persistence-demo # prove Task 07 bounded context and backup/restore replay
make showcase-data # create four varied synthetic cases for the reviewer UI
make security # scan for secrets and known dependency vulnerabilities
make judge   # have Groq grade error recovery across exactly 10 stored traces
```

## Reproduce the synthetic dataset

```bash
./scripts/fetch_dataset_source.sh
make ingest
```

This checks out the pinned public generator, verifies its license and source hashes, generates 10,000 rows with seed 42, and writes ignored artifacts under `data/`. See `docs/DATA_PROVENANCE.md` for checksums, exclusions, and limitations.

## Repository map

- `src/claimtriagelab/`: application package
- `tests/`: automated tests
- `evals/`: evaluation entry points
- `docs/`: architecture, governance, provenance, and implementation plan
- `docs/decision-policy.md`: human authority, forbidden actions, evidence, and retention rules
- `evidence/`: screenshots and notes for each task
- `data/`: ignored local datasets
- `artifacts/`: ignored databases, models, traces, and backups

## Live agent configuration

Copy `.env.example` to `.env.local` and configure one supported model provider, Qdrant Cloud, Langfuse, and the reviewer credentials. Load those variables before starting the app:

```bash
set -a
source .env.local
set +a
.venv/bin/python -m claimtriagelab.cli serve-reviewer \
  --database artifacts/showcase.sqlite3 --reviewer-id showcase_reviewer \
  --host 127.0.0.1 --port 8765
```

New production executions do not fall back to deterministic agent responses when provider credentials are missing. Tests explicitly enable a deterministic fixture path.

## Free hosting boundary

`render.yaml` defines a Docker based Render Free web service. The service uses a prebuilt synthetic showcase database copied into the container and disables public reset. Add all secret values through Render's environment settings. See `docs/deployment.md` for the judge, webhook, container, deployment, and hosted-test commands.

Render Free web services use an ephemeral filesystem. New reviews persist across sign-outs and browser logins while the current instance exists, but Render can remove local changes when the service sleeps, restarts, or redeploys. The verified seed is restored after that event, and Langfuse retains exported cloud traces. Durable user-created workflow state across host restarts requires a free external database adapter before this can be described as durable public hosting.

## Cost boundary

The local path uses open-source software. The hosted showcase is designed for the published free tiers of Render, Groq or Gemini, Qdrant Cloud, and Langfuse. Each provider enforces quotas and can throttle or suspend service when its free allowance is exhausted. The application retries bounded model rate limits and never enables paid overages itself.

## Current limitations

This is a synthetic-data engineering demo. Its labels are generated signals rather than confirmed fraud. It has not been validated for real insurance operations. The reviewer login is a single configured showcase identity rather than a multi-user identity provider. The Render Free filesystem does not retain new local SQLite writes across instance replacement.
