# Architecture overview

ClaimTriageLab follows a local-first modular monolith. The required runtime uses one Python process and a local SQLite database. Later phases add a server-rendered reviewer UI and a bounded LangGraph workflow for pause/resume behavior.

```mermaid
flowchart LR
    A[Synthetic claim intake] --> B[Validation]
    B --> C[Evidence and indicators]
    C --> D[Transparent triage]
    D --> E[Evidence-linked brief]
    E --> F[Human review]
    F --> G[Immutable audit event]
```

The baseline is deterministic and measurable. Optional local models operate behind typed interfaces and cannot authorize actions. Source evidence remains separate from extracted facts and summaries.

