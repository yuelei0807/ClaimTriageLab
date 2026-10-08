# Threat model

## Task 00 boundary

The current scaffold has no network service, dataset, secrets, model, or database. Its primary risks are dependency tampering, accidental inclusion of sensitive files, and misleading claims about project readiness.

## Initial controls

- Locked dependencies and committed project metadata
- Ignored `.env`, local data, databases, model files, and traces
- Local-only architecture decision
- Synthetic-only health report and documentation
- Automated lint and tests

## Task 01 trust-boundary review

| Boundary | Threat | Current control | Later control |
|---|---|---|---|
| Intake to domain | Malformed dates, IDs, amounts, surprise fields, or oversized context | Strict contracts plus document, narrative, retrieval, token, and workflow-step limits | API body-size enforcement in Task 08 |
| Evidence to triage | Uncited or contradictory signals | Indicator evidence IDs must appear in result; unresolved inputs use `insufficient_information` | Verify evidence ownership and source locators in storage |
| Model/tool to reviewer | Automated adverse action or instruction injection | Decision policy restricts authority to human reviewer | Authenticated action endpoint, allowlisted tools, prompt-injection tests |
| Local storage to outputs | Synthetic record or secret disclosure | Ignored paths, pseudonymous IDs, verified SQLite backup/restore | Encrypted backup policy for any future sensitive deployment |
| Packet to extraction | Prompt injection or unsupported assertion | Allowlisted fields, instruction-pattern warning, typed facts, mandatory source links | Broader adversarial packet evaluation |
| Caller to tools | Unauthorized writes, invented tools, malformed input, replay | Basic authentication, CSRF, explicit allowlist, role checks, strict schemas, idempotency, sanitized audit | Replace demo credentials with managed identity for deployment |

Review updated 2026-10-06: Task 05 rejects and audits unknown, malformed, and unauthorized calls. Role claims are passed by trusted application code for now; real authentication and API security remain Task 08 release gates.

The loopback interface now enforces authentication, CSRF protection, HTTP body-size limits, tamper-evident audit verification, and redacted telemetry. A production deployment would still require managed identity, TLS termination, external audit anchoring, encrypted backups, and operational key rotation.
