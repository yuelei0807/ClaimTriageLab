# Model card — Task 03 baselines

## Intended use and versions

`rules-v1` and `logistic-v1` prioritize synthetic auto claims for authorized human review. Their outputs are queue recommendations, not fraud findings or claim decisions. Threshold version `review-capacity-10pct-v1` was selected once on the 1,500-row validation split against a maximum 10% review capacity, then applied unchanged to the 1,500-row frozen holdout.

The rules use claim amount, prior-claim count, reporting delay, severity plus police-report status, claim-to-coverage ratio, and policy activity. Each application result carries rule/model version, threshold version, and evidence IDs. Missing evidence or contradictory dates and amounts route to `insufficient_information`.

The logistic challenger uses 25 intake-time features, including one derived policy-age duration. Direct target flags, their raw generator inputs and deterministic cost proxies, generated score, outcomes, IDs, target, raw dates, age, gender, marital status, occupation, annual income, education level, and credit score are excluded.

## Frozen holdout results

| Baseline | Review rate | Precision | Recall at capacity | Average precision | PR-AUC | Brier |
|---|---:|---:|---:|---:|---:|---:|
| Rules v1 | 5.73% | 0.419 | 0.117 | 0.303 | 0.342 | N/A |
| Logistic v1 | 8.13% | 0.205 | 0.081 | 0.216 | 0.214 | 0.165 |

The logistic confusion matrix is TN 1,094, FP 97, FN 284, TP 25. The rules confusion matrix is TN 1,141, FP 50, FN 273, TP 36. Discrete rule-score ties mean the closest cutoff that stays within capacity reviews 6.87% on validation; the next cutoff would exceed the 10% budget.

Gender is excluded from the model and used only for diagnostic slice evaluation. Female and male holdout recall were 0.103 and 0.056. Severity-slice recall ranges from 0.071 for Moderate to 0.089 for Total Loss. These diagnostics do not establish fairness.

## Artifacts and reproducibility

Run `make baseline` after Task 02 ingestion. It writes an ignored serialized model, `metrics.json`, a precision-recall curve, and a calibration curve under `artifacts/baseline/`. The current model SHA-256 is `e4722f62ab931d08fe89b0b3c9d0c558d42f4ed69ad741cbd747064b5a24a896`.

## Limitations and prohibited use

The label is produced by the same synthetic generator being modeled. Metrics measure imitation of generator relationships, not detection of confirmed real-world fraud. No automatic denial, accusation, claimant contact, or investigation initiation is allowed. Real-claim use requires separate data governance, independent validation, security review, fairness analysis, and jurisdiction review.
