# Task 07 evidence notes

- **Date:** 2026-10-06
- **Task:** Context and persistence controls
- **Expected:** Explicit size, retrieval, token, workflow-step, and retry limits; old-context summarization with provenance; verified SQLite backup/restore; and replay of a long synthetic case.
- **Actual:** Limits are centralized and persisted in workflow state. Long narrative histories retain their source record while only older context is compacted, with hashes and method recorded. A paused workflow can be backed up, restored to another database, and completed with its review audit intact.

## Verification

```bash
make test
make persistence-demo
make verify
```

Tests cover no-op context handling, bounded compaction, source hashes, retrieval-limit rejection, integrity-checked backup and restore, checkpoint recovery, retained source narrative, and authorized completion after restore.

## Limitations and screenshot evidence

The context token count is a deterministic estimate rather than a provider tokenizer. The fallback summary extracts bounded first-sentence text and is intended for navigation, while structured facts and evidence remain authoritative. Backups are integrity-checked but are not encrypted. Actual Task 07 process/result screenshots have not yet been captured.
