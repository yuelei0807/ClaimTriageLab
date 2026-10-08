"""Generate, validate, split, and report on a pinned synthetic dataset source."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from claimtriagelab.ingestion.schema import EXPECTED_COLUMNS, FEATURE_INVENTORY, TARGET

PINNED_SOURCE_COMMIT = "2551a1c77275464906f65daabcd6d208b7d33c32"
PINNED_SOURCE_URL = (
    "https://github.com/MobeenFatimaa/Insurance-Claim-Fraud-Detection-Dataset-Generator.git"
)
GENERATION_SEED = 42
SAMPLE_ROWS = 10_000
SOURCE_CHECKSUMS = {
    "LICENSE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    "scripts/constants.py": "7a5bed8e68b178461de9f8d4307cad3979654a0874d9e2c7da5d9ca883f11d19",
    "scripts/generate_dataset.py": (
        "5c938ba46a3c5b227675c9424eaca69fac2588cc0dd223eda8b2611798d39290"
    ),
    "scripts/utils.py": "7af340bc0589415ea34951c8eb70f39fa20e1b212b6382ce01eeef4301a41ccc",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source(source_dir: Path) -> None:
    required = [
        "LICENSE",
        "scripts/constants.py",
        "scripts/generate_dataset.py",
        "scripts/utils.py",
    ]
    missing = [name for name in required if not (source_dir / name).is_file()]
    if missing:
        raise ValueError(f"source is missing required files: {', '.join(missing)}")
    license_text = (source_dir / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError("source LICENSE is not recognizable as Apache-2.0")
    mismatched = [
        name
        for name, expected in SOURCE_CHECKSUMS.items()
        if sha256_file(source_dir / name) != expected
    ]
    if mismatched:
        raise ValueError(f"source checksum mismatch: {', '.join(mismatched)}")


def _load_generator(source_dir: Path) -> Any:
    scripts_dir = source_dir / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "claimtriagelab_upstream_generator", scripts_dir / "generate_dataset.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load pinned generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts_dir))


def generate_sample(source_dir: Path, rows: int = SAMPLE_ROWS) -> pd.DataFrame:
    validate_source(source_dir)
    generator = _load_generator(source_dir)
    generator.NUM_SAMPLES = rows
    frame = generator.build_dataset()
    if tuple(frame.columns) != EXPECTED_COLUMNS:
        raise ValueError("generated columns do not match the pinned 62-column schema")
    if len(frame) != rows:
        raise ValueError(f"expected {rows} generated rows, received {len(frame)}")
    return frame


def quality_summary(frame: pd.DataFrame) -> dict[str, Any]:
    incident = pd.to_datetime(frame["incident_date"], errors="coerce")
    reported = pd.to_datetime(frame["claim_date"], errors="coerce")
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "duplicate_rows": int(frame.duplicated().sum()),
        "duplicate_claim_ids": int(frame["claim_id"].duplicated().sum()),
        "missing_cells": int(frame.isna().sum().sum()),
        "invalid_incident_dates": int(incident.isna().sum()),
        "invalid_claim_dates": int(reported.isna().sum()),
        "claims_reported_before_incident": int((reported < incident).sum()),
        "class_counts": {
            str(key): int(value) for key, value in frame[TARGET].value_counts().items()
        },
        "class_prevalence": {
            str(key): round(float(value), 6)
            for key, value in frame[TARGET].value_counts(normalize=True).items()
        },
    }


def chronological_split(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ordered = frame.sort_values(["incident_date", "claim_id"], kind="stable").reset_index(drop=True)
    train_end = int(len(ordered) * 0.70)
    validation_end = int(len(ordered) * 0.85)
    return {
        "train": ordered.iloc[:train_end].copy(),
        "validation": ordered.iloc[train_end:validation_end].copy(),
        "holdout": ordered.iloc[validation_end:].copy(),
    }


def run_ingestion(source_dir: Path, output_dir: Path, rows: int = SAMPLE_ROWS) -> dict[str, Any]:
    frame = generate_sample(source_dir, rows)
    raw_dir = output_dir / "raw"
    normalized_dir = output_dir / "normalized"
    holdout_dir = output_dir / "holdout"
    reports_dir = output_dir / "reports"
    for directory in (raw_dir, normalized_dir, holdout_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    raw_filename = "synthetic_claims_10k.csv" if rows == 10_000 else f"synthetic_claims_{rows}.csv"
    raw_path = raw_dir / raw_filename
    frame.to_csv(raw_path, index=False)
    splits = chronological_split(frame)
    split_paths = {
        "train": normalized_dir / "train.csv",
        "validation": normalized_dir / "validation.csv",
        "holdout": holdout_dir / "holdout.csv",
    }
    for name, split in splits.items():
        split.to_csv(split_paths[name], index=False)

    inventory_path = reports_dir / "leakage_inventory.csv"
    pd.DataFrame(asdict(item) for item in FEATURE_INVENTORY).to_csv(inventory_path, index=False)
    report = quality_summary(frame) | {
        "source_url": PINNED_SOURCE_URL,
        "source_commit": PINNED_SOURCE_COMMIT,
        "generation_seed": GENERATION_SEED,
        "license": "Apache-2.0",
        "source_checksums": {name: sha256_file(source_dir / name) for name in SOURCE_CHECKSUMS},
        "raw_sha256": sha256_file(raw_path),
        "splits": {
            name: {
                "rows": int(len(splits[name])),
                "sha256": sha256_file(path),
                "incident_date_min": str(splits[name]["incident_date"].min()),
                "incident_date_max": str(splits[name]["incident_date"].max()),
                "class_counts": {
                    str(key): int(value)
                    for key, value in splits[name][TARGET].value_counts().items()
                },
            }
            for name, path in split_paths.items()
        },
        "feature_actions": pd.Series([item.modeling_action for item in FEATURE_INVENTORY])
        .value_counts()
        .to_dict(),
        "limitations": [
            "All records and labels are synthetic.",
            "The target is generated from weighted rule flags and noise, not confirmed fraud.",
            "Chronological splitting reduces temporal leakage; external validity remains unknown.",
            "Target-generating flags, outcomes, identifiers, and generated score are excluded.",
        ],
    }
    report_path = reports_dir / "quality_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
