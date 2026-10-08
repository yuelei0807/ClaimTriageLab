# Data provenance

## Pinned source

- Repository: `MobeenFatimaa/Insurance-Claim-Fraud-Detection-Dataset-Generator`
- Commit: `2551a1c77275464906f65daabcd6d208b7d33c32` (2026-09-09)
- License: Apache License 2.0, verified from the pinned `LICENSE`
- Generator seed: `42`
- Local development extract: 10,000 generated rows, 62 columns
- Raw SHA-256: `ed1c6a15b825f783a04d07427993ea3daa4676da8bc482cd89f25fbccc48abd2`

The source is fetched by `scripts/fetch_dataset_source.sh`. Ingestion verifies SHA-256 hashes for the license and three generator files before executing them. Generated files stay under ignored `data/`.

The pinned repository has no committed CSV or `docs/DATA_DICTIONARY.md` despite its README. ClaimTriageLab generates the extract from pinned code and maintains an explicit schema and leakage inventory. Some upstream comments also say 60 fields; actual ordered output has 62.

## Quality and splits

The extract contains 7,930 `No` and 2,070 `Yes` labels, a synthetic positive prevalence of 20.7%. It has zero missing cells, duplicate rows, duplicate claim IDs, invalid dates, or reports before incidents.

| Split | Rows | Incident dates | SHA-256 |
|---|---:|---|---|
| Train | 7,000 | 2021-01-01 to 2024-07-16 | `6c2c2080dab4fd668c887b10240c21f7e8420c656d7bf63bfdbf47ac448d0e42` |
| Validation | 1,500 | 2024-07-17 to 2025-04-14 | `a1fd51f8edafa336784aec9e349d0151e486a4038bcdfcd1e6a47e2f8c0b7c8d` |
| Frozen holdout | 1,500 | 2025-04-15 to 2025-12-30 | `48698e853de9c3227bad6e25a4e0919330740889fb129f60bbfc7fdc3a3b0640` |

Raw, development, and holdout files are stored separately under `data/raw`, `data/normalized`, and `data/holdout`. Machine-readable quality and leakage reports are under `data/reports`.

## Leakage inventory

Every field is classified in `src/claimtriagelab/ingestion/schema.py` and emitted with `available_at_intake`, action, and reason. There are 34 candidates, 27 exclusions, and one target.

- Exclude identifiers/name: `claim_id`, `policy_id`, `customer_id`, `customer_name`.
- Exclude outcomes: `claim_status`, `approved_amount`, `claim_duration_days`, `payout_amount`.
- Exclude generated score: `fraud_risk_score`.
- Exclude direct target rules: `suspicious_documents`, `claim_submitted_at_night`, `multiple_claims_last_year`, `delayed_reporting`, `inconsistent_statements`, `gps_location_match`, `repair_shop_verified`, `identity_verified`, `claim_history_risk`.
- Exclude raw generator inputs and deterministic cost proxies: `claim_amount`, `previous_claims`, `police_report`, `accident_severity`, `repair_cost`, `medical_cost`, `towing_cost`, `rental_vehicle_cost`, and `total_loss`.
- Use `fraudulent` only as the synthetic target.

The remaining 34 fields are Task 03 candidates. The logistic baseline applies an additional application-level exclusion for protected and socioeconomic fields and raw dates.

## Limitations

The target is a weighted rule output plus noise, not adjudicated fraud. A model can learn generator structure even after direct leakage removal. Chronological splitting prevents date-range overlap but gives no real-world validity. Real claimant or policyholder data is prohibited.
