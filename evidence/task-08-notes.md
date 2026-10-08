# Task 08 evidence notes

- **Date:** 2026-10-06
- **Task:** Observability and security
- **Actual:** Reviewer actions require credentials and CSRF validation, write bodies are bounded, tool and workflow spans contain sanitized operational metadata, audit events have an immutable verifiable hash chain, and automated secret and dependency scans pass.

## Verification

```bash
make test
make security
make verify
```

Deliberate tests cover missing credentials, invalid CSRF, oversized bodies, direct audit-row tampering, and trace payload redaction. The dependency audit initially identified `PYSEC-2026-1845` in pytest 8.4.2; pytest was upgraded and the repeated audit reported no known vulnerabilities.

## Limitations

The signed local session is suitable for this loopback research demo, not a multi-user identity system. Credentials are process environment values. Audit hashes are not externally anchored, and telemetry currently relies on the configured local OpenTelemetry provider rather than a durable collector.
