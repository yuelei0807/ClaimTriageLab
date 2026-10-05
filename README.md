# ClaimTriageLab

ClaimTriageLab is a zero-cost, local-first research project for prioritizing synthetic auto-insurance claims for human review. It produces review recommendations and evidence references. It does not determine fraud, deny claims, or take action against a claimant.

## Phase 1 status

Task 00 establishes a reproducible Python repository, local health check, tests, linting, evaluation placeholder, and implementation evidence. No dataset or real claim information is included yet.

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
```

## Repository map

- `src/claimtriagelab/`: application package
- `tests/`: automated tests
- `evals/`: evaluation entry points
- `docs/`: architecture, governance, provenance, and implementation plan
- `evidence/`: screenshots and notes for each task
- `data/`: ignored local datasets
- `artifacts/`: ignored databases, models, traces, and backups

## Cost boundary

The required path runs on the existing Mac with open-source software and no paid API, cloud service, or billing account. Electricity, internet access, and existing hardware are not counted as service charges. Optional public demos and optional model providers are outside the required path.

## Current limitations

This is an engineering scaffold using synthetic-data boundaries. It has not ingested a dataset, trained a model, or been validated for real insurance operations.

