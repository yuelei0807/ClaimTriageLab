"""Schema and leakage classifications for the pinned upstream dataset."""

from __future__ import annotations

from dataclasses import dataclass

EXPECTED_COLUMNS = (
    "claim_id",
    "policy_id",
    "customer_id",
    "customer_name",
    "claim_date",
    "incident_date",
    "claim_status",
    "claim_amount",
    "approved_amount",
    "deductible",
    "claim_duration_days",
    "age",
    "gender",
    "marital_status",
    "occupation",
    "annual_income",
    "education_level",
    "credit_score",
    "years_with_company",
    "previous_claims",
    "policy_type",
    "policy_start_date",
    "policy_duration_years",
    "premium_amount",
    "coverage_amount",
    "deductible_plan",
    "payment_method",
    "policy_active",
    "incident_type",
    "accident_severity",
    "incident_location",
    "weather_condition",
    "police_report",
    "witnesses",
    "injuries",
    "hospital_visit",
    "property_damage",
    "vehicle_damage",
    "vehicle_make",
    "vehicle_model",
    "vehicle_year",
    "vehicle_age",
    "mileage",
    "vehicle_value",
    "ownership_type",
    "suspicious_documents",
    "claim_submitted_at_night",
    "multiple_claims_last_year",
    "delayed_reporting",
    "inconsistent_statements",
    "gps_location_match",
    "repair_shop_verified",
    "identity_verified",
    "claim_history_risk",
    "fraud_risk_score",
    "repair_cost",
    "medical_cost",
    "towing_cost",
    "rental_vehicle_cost",
    "total_loss",
    "payout_amount",
    "fraudulent",
)

TARGET = "fraudulent"
DIRECT_RULE_FLAGS = {
    "suspicious_documents",
    "claim_submitted_at_night",
    "multiple_claims_last_year",
    "delayed_reporting",
    "inconsistent_statements",
    "gps_location_match",
    "repair_shop_verified",
    "identity_verified",
    "claim_history_risk",
}
DOWNSTREAM_FIELDS = {
    "claim_status",
    "approved_amount",
    "claim_duration_days",
    "payout_amount",
}
GENERATED_SCORE_FIELDS = {"fraud_risk_score"}
DIRECT_IDENTIFIERS = {"claim_id", "policy_id", "customer_id", "customer_name"}
TARGET_GENERATING_PRECURSORS = {
    "claim_amount",
    "previous_claims",
    "police_report",
    "accident_severity",
    "repair_cost",
    "medical_cost",
    "towing_cost",
    "rental_vehicle_cost",
    "total_loss",
}


@dataclass(frozen=True)
class FeatureClassification:
    feature: str
    available_at_intake: bool
    modeling_action: str
    reason: str


def classify_feature(feature: str) -> FeatureClassification:
    """Return the conservative intake-time and modeling classification for one field."""
    if feature == TARGET:
        return FeatureClassification(feature, False, "target_only", "generated target label")
    if feature in GENERATED_SCORE_FIELDS:
        return FeatureClassification(feature, False, "exclude", "score used to create target")
    if feature in DIRECT_RULE_FLAGS:
        return FeatureClassification(feature, True, "exclude", "direct target-generating rule flag")
    if feature in TARGET_GENERATING_PRECURSORS:
        return FeatureClassification(
            feature, True, "exclude", "raw input or deterministic proxy used by target generator"
        )
    if feature in DOWNSTREAM_FIELDS:
        return FeatureClassification(feature, False, "exclude", "post-intake claim outcome")
    if feature in DIRECT_IDENTIFIERS:
        return FeatureClassification(feature, True, "exclude", "identifier or synthetic name")
    return FeatureClassification(feature, True, "candidate", "plausibly known at claim intake")


FEATURE_INVENTORY = tuple(classify_feature(column) for column in EXPECTED_COLUMNS)
MODEL_CANDIDATES = tuple(
    item.feature for item in FEATURE_INVENTORY if item.modeling_action == "candidate"
)
