# Showcase reviewer experience

The pre-Task 09 product pass turns the workflow endpoint into a reviewer-facing application:

- Branded sign-in with signed, HTTP-only session cookies.
- Queue dashboard with pending/completed counts and live audit-integrity status.
- Four reproducible synthetic cases covering priority, routine, insufficient-information, pending, and completed states.
- Case summary cards for amount, coverage, severity, and reporting date.
- Plain-language signal explanations linked to the exact evidence records used by each rule.
- Workflow progress, rule and threshold versions, evidence count, and verified audit-chain status.
- Explicit human-authority warning and three decision choices with rationale guidance.
- Server-generated hidden idempotency keys.
- Append-only follow-up reviews for completed cases, with every earlier decision retained.
- One-click demo reset from the dashboard; no terminal or server restart is required.
- Responsive layout for narrow and desktop viewports.

Create the showcase data and launch the app:

```bash
make showcase-data
export CLAIMTRIAGE_REVIEWER_PASSWORD='replace-this-value'
export CLAIMTRIAGE_CSRF_SECRET='replace-this-value-too'
uv run claimtriagelab serve-reviewer --database artifacts/showcase.sqlite3
```

The dashboard's **Reset demo cases** action recreates the canonical four-case dataset after a confirmation prompt. This intentionally discards the current synthetic demo decisions. The public-hosting phase must supply strong platform secrets, HTTPS, durable volume handling or deterministic reseeding, health checks, and an explicit shared-demo reset policy.
