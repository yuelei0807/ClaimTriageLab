# Task 09 evidence — evaluation and deployment

Date: 2026-10-08

## LLM judge

- Input: latest 10 persisted traces from `artifacts/showcase.sqlite3`
- Provider/model: Groq `openai/gpt-oss-20b`
- Validated output: `output/task9_llm_judge.json`
- Result: 10 traces, mean 4.2/5, distribution `{1: 1, 4: 4, 5: 5}`
- The script rejects missing, duplicate, unexpected trace IDs, scores outside 1–5, and cited run
  IDs that do not belong to the evaluated trace.

## Deployment checks

- `ruff check` and `ruff format --check`: pass
- Test suite: 65 passed
- Secret scan: pass
- Dependency lock check: pass
- Python wheel build: pass
- Render blueprint: Docker runtime and free plan validated
- Hosted entry point `/healthz`: HTTP 200
- Hosted webhook with API key: HTTP 200
- Real continuation: Groq model response with Qdrant evidence IDs and a persisted trace ID

The end-to-end hosted smoke test used a disposable SQLite copy on local port 8766. Public Render
deployment remains an account action: the Render dashboard requires sign-in and this checkout has no
Git remote for Render to clone. The local reviewer remains available on port 8765.
