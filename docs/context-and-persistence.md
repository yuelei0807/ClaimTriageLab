# Context and persistence controls

Task 07 centralizes runtime bounds in `src/claimtriagelab/limits.py`:

| Limit | Value |
|---|---:|
| Maximum document size | 5 MiB |
| Maximum evidence records per case retrieval | 50 |
| Narrative context budget | 1,200 estimated tokens |
| Maximum workflow steps | 12 |
| Tool retry attempts | 3 |
| Maximum narrative-history items | 100 |

The token estimate is deterministic and conservative at approximately four characters per token. The workflow persists the exact limit configuration with each case checkpoint.

## Narrative provenance

The complete narrative history remains in the claim record as source data. If it fits the context budget, the workflow keeps it unchanged. If it exceeds the budget, it keeps recent entries verbatim and creates a deterministic bounded summary from older entries. The checkpoint records the compaction method, number of summarized items, SHA-256 of every summarized source item, and the original estimated token count. An individual latest entry that cannot fit is rejected instead of silently truncated.

Structured claim fields and evidence IDs remain the source of truth for triage. Narrative summaries do not create indicators or authorize review actions.

## Backup and restore

`backup_database()` uses SQLite's online backup API so WAL state is included consistently. It runs `PRAGMA integrity_check` before publishing the backup. Restore verifies the source backup, writes a temporary database, verifies it, and atomically replaces the closed destination.

The commands are:

```bash
uv run claimtriagelab backup-database --database artifacts/workflow.sqlite3 --output artifacts/backups/workflow.sqlite3
uv run claimtriagelab restore-database --backup artifacts/backups/workflow.sqlite3 --database artifacts/restored.sqlite3
```

Stop the service before replacing its active database. `make persistence-demo` pauses a long synthetic case, backs it up, restores it to a separate database, resumes it, and writes the replay proof to `artifacts/persistence-demo/report.json`.
