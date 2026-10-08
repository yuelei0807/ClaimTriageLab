"""Task 02 dataset validation, splitting, and leakage controls."""

from pathlib import Path

import pandas as pd
import pytest

from claimtriagelab.ingestion.pipeline import chronological_split, quality_summary, validate_source
from claimtriagelab.ingestion.schema import (
    EXPECTED_COLUMNS,
    FEATURE_INVENTORY,
    MODEL_CANDIDATES,
    TARGET_GENERATING_PRECURSORS,
)


def sample_frame(rows: int = 20) -> pd.DataFrame:
    data = {column: [f"value-{index}" for index in range(rows)] for column in EXPECTED_COLUMNS}
    data["claim_id"] = [f"CLM-{index:07d}" for index in range(rows)]
    data["incident_date"] = pd.date_range("2024-01-01", periods=rows).strftime("%Y-%m-%d").tolist()
    data["claim_date"] = pd.date_range("2024-01-02", periods=rows).strftime("%Y-%m-%d").tolist()
    data["fraudulent"] = ["Yes" if index % 5 == 0 else "No" for index in range(rows)]
    return pd.DataFrame(data, columns=EXPECTED_COLUMNS)


def test_every_feature_has_a_leakage_classification() -> None:
    assert len(FEATURE_INVENTORY) == len(EXPECTED_COLUMNS) == 62
    assert {item.feature for item in FEATURE_INVENTORY} == set(EXPECTED_COLUMNS)
    assert "fraudulent" not in MODEL_CANDIDATES
    assert "fraud_risk_score" not in MODEL_CANDIDATES
    assert "suspicious_documents" not in MODEL_CANDIDATES
    assert "payout_amount" not in MODEL_CANDIDATES
    assert not TARGET_GENERATING_PRECURSORS & set(MODEL_CANDIDATES)


def test_chronological_split_is_70_15_15_and_non_overlapping() -> None:
    splits = chronological_split(sample_frame())
    assert {name: len(frame) for name, frame in splits.items()} == {
        "train": 14,
        "validation": 3,
        "holdout": 3,
    }
    ids = [set(frame["claim_id"]) for frame in splits.values()]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    assert splits["train"]["incident_date"].max() <= splits["validation"]["incident_date"].min()
    assert splits["validation"]["incident_date"].max() <= splits["holdout"]["incident_date"].min()


def test_quality_summary_detects_anomalies() -> None:
    frame = sample_frame()
    frame.loc[1, "claim_id"] = frame.loc[0, "claim_id"]
    frame.loc[2, "claim_date"] = "2020-01-01"
    frame.loc[3, "incident_date"] = "not-a-date"
    report = quality_summary(frame)
    assert report["duplicate_claim_ids"] == 1
    assert report["claims_reported_before_incident"] == 1
    assert report["invalid_incident_dates"] == 1
    assert report["class_counts"] == {"No": 16, "Yes": 4}


def test_source_requires_apache_license_and_generator(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing required files"):
        validate_source(tmp_path)
