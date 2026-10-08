"""Run the Task 9 LLM judge against ten persisted historical traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from claimtriagelab.evaluation import judge_historical_traces


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("artifacts/showcase.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("output/task9_llm_judge.json"))
    args = parser.parse_args()
    result = judge_historical_traces(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("trace_count", "mean_score", "model")}))


if __name__ == "__main__":
    main()
