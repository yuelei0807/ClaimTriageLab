"""Model feature safety and fixed-capacity metric tests."""

import numpy as np

from claimtriagelab.models.baseline import (
    MODEL_FEATURES,
    PROTECTED_OR_SOCIOECONOMIC,
    TARGET_GENERATING_PRECURSORS,
    binary_metrics,
    capacity_threshold,
)


def test_model_features_exclude_leakage_and_sensitive_fields() -> None:
    forbidden = {
        "fraudulent",
        "fraud_risk_score",
        "suspicious_documents",
        "payout_amount",
    }
    assert not forbidden & set(MODEL_FEATURES)
    assert not PROTECTED_OR_SOCIOECONOMIC & set(MODEL_FEATURES)
    assert not TARGET_GENERATING_PRECURSORS & set(MODEL_FEATURES)
    assert "reporting_delay_days" not in MODEL_FEATURES


def test_capacity_threshold_selects_top_ten_percent() -> None:
    scores = np.arange(100, dtype=float) / 100
    threshold = capacity_threshold(scores, 0.10)
    assert threshold == 0.90
    assert int((scores >= threshold).sum()) == 10


def test_binary_metrics_report_confusion_and_capacity_recall() -> None:
    labels = np.array([0, 0, 1, 1])
    scores = np.array([0.1, 0.8, 0.7, 0.9])
    metrics = binary_metrics(labels, scores, 0.75, probability_scores=True)
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["precision"] == 0.5
    assert metrics["recall_at_capacity"] == 0.5
    assert metrics["average_precision"] == 0.833333
    assert metrics["pr_auc"] == 0.791667
    assert metrics["brier_score"] == 0.1875


def test_rule_metrics_do_not_report_probability_calibration() -> None:
    labels = np.array([0, 1])
    scores = np.array([0.0, 0.2])
    metrics = binary_metrics(labels, scores, 0.1, probability_scores=False)
    assert metrics["brier_score"] is None
