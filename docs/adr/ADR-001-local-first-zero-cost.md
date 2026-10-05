# ADR-001: Local-first, zero-cost required path

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

The project must incur no required service charge and must remain reproducible on the existing Mac. Free cloud tiers can sleep, expire, change limits, or expose synthetic traces to a third party.

## Decision

The required path runs locally with Python, SQLite, open-source packages, and optional local inference. No billing account, paid API, hosted vector database, or managed observability service is required. The application binds to `127.0.0.1` by default. Public hosting remains an optional synthetic-data demonstration.

## Consequences

- The project works offline after dependencies and data have been downloaded.
- The Mac's available memory and disk limit optional local model choices.
- Continuous public availability is outside the zero-cost guarantee.
- Every optional external service must have a local fallback and separate privacy review.

