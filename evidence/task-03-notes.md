# Task 03 evidence notes

- **Date:** 2026-10-05
- **Task:** Baseline triage engine
- **Expected:** Transparent rules, leakage-safe challenger, validation-only capacity threshold, frozen holdout metrics, uncertainty fallback, versions, and evidence links.
- **Actual:** `rules-v1` and `logistic-v1` were evaluated at threshold version `review-capacity-10pct-v1`. After excluding all known target-generator precursors, the logistic model reviewed 8.13% of holdout cases with precision 0.205, recall 0.081, average precision 0.216, PR-AUC 0.214, and Brier 0.165. All metrics describe synthetic generator labels.

## What changed and why

Added six transparent intake-time indicators and deterministic routing. Missing inputs, missing evidence, reversed dates, claims above coverage, and malformed values route to `insufficient_information`. Added a logistic regression pipeline using 25 leakage-controlled inputs; direct generator flags, their raw precursors and cost proxies, outcomes, identifiers, target, raw dates, and protected or socioeconomic fields are excluded. Thresholds are chosen only on validation data, with discrete ties kept within the 10% review budget.

## Verification

```bash
make test
make baseline
make verify
```

The run writes `metrics.json`, serialized model, precision-recall curve, and calibration curve under ignored `artifacts/baseline/`. Model SHA-256: `e4722f62ab931d08fe89b0b3c9d0c558d42f4ed69ad741cbd747064b5a24a896`.

## Limitations and screenshot evidence

The challenger mostly learns synthetic generator relationships and misses 250 of 309 positive holdout labels at the fixed budget. Severity-slice recall varies widely. This is insufficient for real-world use. Actual Task 03 process and result screenshots have not been captured; the evidence gate remains open and no screenshots were manufactured.
