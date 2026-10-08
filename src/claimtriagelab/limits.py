"""Central resource limits for the local synthetic-claim workflow."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ResourceLimits:
    max_document_bytes: int = 5 * 1024 * 1024
    max_retrieved_evidence: int = 50
    max_context_tokens: int = 1_200
    max_workflow_steps: int = 12
    tool_retry_budget: int = 3
    max_narrative_items: int = 100

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


DEFAULT_LIMITS = ResourceLimits()
