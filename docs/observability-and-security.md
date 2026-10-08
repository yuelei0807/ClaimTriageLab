# Observability and security

Task 08 emits OpenTelemetry spans for tool calls and workflow start/resume operations. Attributes are limited to correlation ID, sanitized operation name, status, latency, retry count, workflow version, error code, and estimated token count. Review reasons, document text, raw tool payloads, secrets, and chain-of-thought are excluded.

The reviewer server provides a branded sign-in form using credentials loaded from `CLAIMTRIAGE_REVIEWER_PASSWORD` and `CLAIMTRIAGE_CSRF_SECRET`. Successful sign-in creates an HTTP-only, same-site, signed session cookie. Login and review forms carry HMAC CSRF tokens. POST, PUT, and PATCH bodies are limited to 16 KiB, and the CLI remains restricted to a loopback bind.

Audit rows remain protected by update/delete triggers. A separate immutable table links each event to the previous event with SHA-256; `verify_audit_integrity()` recomputes the chain and rejects modified events. The chain is local and is not externally anchored, so secure off-device anchoring remains necessary for a production evidentiary system.

Run `make security` for a high-confidence source secret scan and `pip-audit`. The Task 08 run found a vulnerable pytest release, upgraded it to a patched 9.x release, and then completed with no known dependency vulnerabilities.
