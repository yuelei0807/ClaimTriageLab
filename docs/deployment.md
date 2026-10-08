# Task 9 evaluation and free deployment

## LLM judge

The judge reads the latest ten persisted traces from `artifacts/showcase.sqlite3`, sends their run
sequence and deterministic findings to Groq, validates that the model graded every requested trace,
and writes an auditable result to `output/task9_llm_judge.json`.

```bash
set -a
source .env.local
set +a
make judge
```

The 1–5 rubric is embedded in `src/claimtriagelab/evaluation/llm_judge.py`. The output records the
judge provider and model, every trace ID, supporting run IDs, rationales, and aggregate scores. This
secondary evaluation does not replace deterministic grounding, contract, sequence, or context checks.

## Webhook API

Set a long random `CLAIMTRIAGE_WEBHOOK_API_KEY`, then send an authenticated human decision:

```bash
curl -X POST "http://127.0.0.1:8765/api/v1/cases/claim_showcase_priority/reviews" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CLAIMTRIAGE_WEBHOOK_API_KEY" \
  -d '{
    "decision": "approve_referral",
    "reason": "The documented high-value collision warrants specialist investigation.",
    "idempotency_key": "task9-host-test-0001",
    "actor_id": "deployment_tester"
  }'
```

The endpoint resumes the same LangGraph workflow used by the UI. Its response includes the durable
thread ID, the new trace ID, the final stage, and the real model continuation.

## Docker and Render Free

Build and test locally when Docker is available:

```bash
docker build -t claimtriagelab:task9 .
docker run --rm -p 10000:10000 --env-file .env.local claimtriagelab:task9
curl http://127.0.0.1:10000/healthz
```

`render.yaml` declares a Docker based Render Free web service. Push the repository to GitHub or
GitLab, choose **New > Blueprint** in Render, connect the repository, and select the free instance.
Enter each secret marked `sync: false`; Render generates the CSRF and webhook secrets. Deploy and
test `https://<service>.onrender.com/healthz`, then repeat the webhook request with the hosted URL.

Render Free can sleep after inactivity and its filesystem is ephemeral. A sleeping instance may have
a cold start, and a restart restores the verified synthetic seed. Langfuse retains exported traces,
but reviews added to the Render SQLite copy are not durable across instance replacement. No billing
or paid resource is required by this configuration, although Groq, Qdrant, Langfuse, and Render each
enforce their own free quotas.
