"""Deterministic project health checks."""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass

from claimtriagelab import __version__


@dataclass(frozen=True)
class HealthReport:
    status: str
    project: str
    version: str
    python_version: str
    mode: str
    data_classification: str
    service_cost_usd: int

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def build_health_report() -> HealthReport:
    """Build the local Phase 1 health report without external services."""
    return HealthReport(
        status="ok",
        project="ClaimTriageLab",
        version=__version__,
        python_version=platform.python_version(),
        mode="local_research_demo",
        data_classification="synthetic_only",
        service_cost_usd=0,
    )
