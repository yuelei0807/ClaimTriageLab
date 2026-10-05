.PHONY: setup health lint format test eval verify

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

verify: lint test eval health

