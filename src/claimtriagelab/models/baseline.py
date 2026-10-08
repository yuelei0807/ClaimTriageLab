"""Train and evaluate rules and logistic-regression triage baselines."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    auc,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from claimtriagelab.indicators.rules import RULE_VERSION, rule_score
from claimtriagelab.ingestion.schema import MODEL_CANDIDATES, TARGET, TARGET_GENERATING_PRECURSORS

MODEL_VERSION = "logistic-v1"
THRESHOLD_VERSION = "review-capacity-10pct-v1"
REVIEW_CAPACITY = 0.10
PROTECTED_OR_SOCIOECONOMIC = {
    "age",
    "gender",
    "marital_status",
    "occupation",
    "annual_income",
    "education_level",
    "credit_score",
}
DATE_COLUMNS = {"claim_date", "incident_date", "policy_start_date"}
MODEL_FEATURES = tuple(
    feature
    for feature in MODEL_CANDIDATES
    if feature not in PROTECTED_OR_SOCIOECONOMIC | DATE_COLUMNS | TARGET_GENERATING_PRECURSORS
) + ("policy_age_days",)


def prepare_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive intake-time durations and return the frozen model feature set."""
    prepared = frame.copy()
    incident_date = pd.to_datetime(prepared["incident_date"], errors="coerce")
    policy_start = pd.to_datetime(prepared["policy_start_date"], errors="coerce")
    prepared["policy_age_days"] = (incident_date - policy_start).dt.days
    return prepared.loc[:, MODEL_FEATURES]


def build_model(frame: pd.DataFrame) -> Pipeline:
    features = prepare_features(frame)
    numeric = features.select_dtypes(include="number").columns.tolist()
    categorical = [column for column in features.columns if column not in numeric]
    preprocessing = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ]
    )
    return Pipeline(
        [
            ("preprocess", preprocessing),
            ("classifier", LogisticRegression(max_iter=1_000, random_state=42)),
        ]
    )


def capacity_threshold(scores: np.ndarray, capacity: float = REVIEW_CAPACITY) -> float:
    """Choose the fullest validation cutoff whose ties do not exceed capacity."""
    if not 0 < capacity < 1:
        raise ValueError("capacity must be between zero and one")
    unique_scores = np.unique(scores)
    eligible = [score for score in unique_scores if float((scores >= score).mean()) <= capacity]
    if not eligible:
        return float(np.nextafter(scores.max(), np.inf))
    return float(min(eligible))


def binary_metrics(
    labels: np.ndarray, scores: np.ndarray, threshold: float, *, probability_scores: bool
) -> dict[str, Any]:
    predictions = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision_curve, recall_curve, _ = precision_recall_curve(labels, scores)
    return {
        "threshold": round(float(threshold), 8),
        "reviewed": int(predictions.sum()),
        "review_rate": round(float(predictions.mean()), 6),
        "precision": round(float(precision_score(labels, predictions, zero_division=0)), 6),
        "recall": round(float(recall_score(labels, predictions, zero_division=0)), 6),
        "recall_at_capacity": round(float(recall_score(labels, predictions, zero_division=0)), 6),
        "average_precision": round(float(average_precision_score(labels, scores)), 6),
        "pr_auc": round(float(auc(recall_curve, precision_curve)), 6),
        "brier_score": (
            round(float(brier_score_loss(labels, scores)), 6) if probability_scores else None
        ),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "false_referrals": int(fp),
        "missed_referrals": int(fn),
    }


def slice_metrics(
    frame: pd.DataFrame, labels: np.ndarray, scores: np.ndarray, threshold: float
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for column in ("gender", "accident_severity"):
        groups: dict[str, Any] = {}
        for value in sorted(frame[column].astype(str).unique()):
            mask = frame[column].astype(str).to_numpy() == value
            if int(mask.sum()) < 50:
                continue
            group_labels = labels[mask]
            predictions = scores[mask] >= threshold
            groups[value] = {
                "rows": int(mask.sum()),
                "positive_rate": round(float(group_labels.mean()), 6),
                "review_rate": round(float(predictions.mean()), 6),
                "precision": round(
                    float(precision_score(group_labels, predictions, zero_division=0)), 6
                ),
                "recall": round(float(recall_score(group_labels, predictions, zero_division=0)), 6),
            }
        report[column] = groups
    return report


def _write_curves(labels: np.ndarray, scores: np.ndarray, output_dir: Path) -> None:
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    pd.DataFrame(
        {
            "recall": recall[:-1],
            "precision": precision[:-1],
            "threshold": thresholds,
        }
    ).to_csv(output_dir / "precision_recall_curve.csv", index=False)
    observed, predicted = calibration_curve(labels, scores, n_bins=10, strategy="quantile")
    pd.DataFrame({"predicted": predicted, "observed": observed}).to_csv(
        output_dir / "calibration_curve.csv", index=False
    )


def train_and_evaluate(data_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Train on development data, select cutoffs on validation, evaluate frozen holdout."""
    train = pd.read_csv(data_dir / "normalized/train.csv", keep_default_na=False)
    validation = pd.read_csv(data_dir / "normalized/validation.csv", keep_default_na=False)
    holdout = pd.read_csv(data_dir / "holdout/holdout.csv", keep_default_na=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    train_labels = (train[TARGET] == "Yes").astype(int).to_numpy()
    validation_labels = (validation[TARGET] == "Yes").astype(int).to_numpy()
    holdout_labels = (holdout[TARGET] == "Yes").astype(int).to_numpy()

    started = time.perf_counter()
    model = build_model(train)
    model.fit(prepare_features(train), train_labels)
    validation_scores = model.predict_proba(prepare_features(validation))[:, 1]
    model_threshold = capacity_threshold(validation_scores)
    holdout_scores = model.predict_proba(prepare_features(holdout))[:, 1]
    latency_ms = (time.perf_counter() - started) * 1_000

    validation_rule_scores = validation.apply(
        lambda row: rule_score(row.to_dict()), axis=1
    ).to_numpy()
    rule_threshold = capacity_threshold(validation_rule_scores)
    holdout_rule_scores = holdout.apply(lambda row: rule_score(row.to_dict()), axis=1).to_numpy()
    report = {
        "dataset": {
            "train_rows": len(train),
            "validation_rows": len(validation),
            "holdout_rows": len(holdout),
            "holdout_positive_rate": round(float(holdout_labels.mean()), 6),
        },
        "review_capacity": REVIEW_CAPACITY,
        "threshold_version": THRESHOLD_VERSION,
        "threshold_selected_on": "validation",
        "rules": {
            "version": RULE_VERSION,
            "validation": binary_metrics(
                validation_labels,
                validation_rule_scores,
                rule_threshold,
                probability_scores=False,
            ),
            "holdout": binary_metrics(
                holdout_labels, holdout_rule_scores, rule_threshold, probability_scores=False
            ),
        },
        "logistic": {
            "version": MODEL_VERSION,
            "features": list(MODEL_FEATURES),
            "excluded_sensitive_features": sorted(PROTECTED_OR_SOCIOECONOMIC),
            "excluded_target_precursors": sorted(TARGET_GENERATING_PRECURSORS),
            "fit_and_score_latency_ms": round(latency_ms, 3),
            "validation": binary_metrics(
                validation_labels,
                validation_scores,
                model_threshold,
                probability_scores=True,
            ),
            "holdout": binary_metrics(
                holdout_labels, holdout_scores, model_threshold, probability_scores=True
            ),
            "holdout_slices": slice_metrics(
                holdout, holdout_labels, holdout_scores, model_threshold
            ),
        },
        "limitations": [
            "Metrics measure synthetic generator labels, not real-world fraud.",
            "The model may learn generator-specific relationships despite leakage controls.",
            "Slice metrics are diagnostic and do not establish fairness or legal suitability.",
        ],
    }
    joblib.dump(model, output_dir / "logistic-v1.joblib")
    _write_curves(holdout_labels, holdout_scores, output_dir)
    (output_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
