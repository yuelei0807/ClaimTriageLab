# Task 04 evidence notes

- **Date:** 2026-10-05
- **Task:** Evidence extraction and case brief
- **Expected:** Synthetic PDF/text packets, typed extraction, mandatory source locators, deterministic fallback briefs, prompt-injection tests, and unsupported-assertion blocking.
- **Actual:** Two reproducible one-page PDFs and two cited Markdown briefs were created. Thirty tests pass, including PDF extraction, prompt-injection quarantine, conflict and missing-item sections, citation validation, and unsupported assertion rejection.

## What changed and why

Added 5 MiB document limits, allowlisted field extraction, stable source/fact/evidence hashes, page links, typed quality flags, deterministic brief generation, and a document-instruction detector. The adversarial narrative is retained as untrusted evidence metadata, excluded from verified factual prose, and surfaced to the reviewer as a warning.

## Verification

```bash
make briefs
make test
make verify
```

The PDFs were regenerated twice with identical SHA-256 hashes. Both final pages were rendered at 144 DPI and visually inspected for clipping, overlap, wrapping, and legibility.

## Limitations and screenshot evidence

Extraction handles stable, text-based, allowlisted synthetic packets; OCR, scanned forms, multi-document reconciliation, and arbitrary layouts are future work. The injection detector is a bounded safeguard rather than a complete semantic security system. Actual Task 04 process/result screenshots have not been captured, so that evidence gate remains open.
