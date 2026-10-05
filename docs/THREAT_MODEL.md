# Threat model

## Task 00 boundary

The current scaffold has no network service, dataset, secrets, model, or database. Its primary risks are dependency tampering, accidental inclusion of sensitive files, and misleading claims about project readiness.

## Initial controls

- Locked dependencies and committed project metadata
- Ignored `.env`, local data, databases, model files, and traces
- Local-only architecture decision
- Synthetic-only health report and documentation
- Automated lint and tests

Later phases will add input size limits, authentication, CSRF protection, immutable audit events, prompt-injection tests, redacted telemetry, and backup/restore checks before exposing a reviewer interface.

