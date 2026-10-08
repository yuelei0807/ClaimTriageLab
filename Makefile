.PHONY: setup health lint format test eval judge ingest baseline packets briefs tools-demo workflow-demo persistence-demo showcase-data security verify

setup:
	uv sync --dev

health:
	uv run claimtriagelab health --json

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

eval:
	uv run python evals/run_evaluation.py

judge:
	uv run python evals/llm_judge.py

ingest:
	uv run claimtriagelab ingest --source-dir data/source/insurance-claim-generator --output-dir data

baseline:
	uv run claimtriagelab train-baseline --data-dir data --output-dir artifacts/baseline

packets:
	uv run python scripts/create_sample_packets.py

briefs: packets
	uv run claimtriagelab build-brief --packet output/pdf/routine-claim-packet.pdf --output output/briefs/routine-claim-brief.md
	uv run claimtriagelab build-brief --packet output/pdf/ambiguous-injection-packet.pdf --output output/briefs/ambiguous-injection-brief.md

tools-demo:
	uv run python scripts/run_tools_demo.py

workflow-demo:
	uv run python scripts/run_workflow_demo.py

persistence-demo:
	uv run python scripts/run_persistence_demo.py

showcase-data:
	uv run python scripts/prepare_showcase.py

security:
	uv run python scripts/scan_secrets.py
	uv run pip-audit

verify: lint test eval health
