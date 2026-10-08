# Decision policy — synthetic research demo

## Scope and authority

ClaimTriageLab prioritizes synthetic auto claims for an authorized human reviewer. `routine_review`, `priority_review`, and `insufficient_information` are queue categories, not fraud findings or claim outcomes. A score is a research signal only. No automated output may deny or reduce a claim, accuse a person, contact a claimant, request a live external lookup, or start an investigation.

Only an authorized reviewer may approve a referral, reject it, or request information. The reviewer must give a reason. Future UI and workflow code must enforce authorization at the action boundary and record an immutable audit event. A model, retrieved document, tool response, or prompt cannot grant review authority.

## Evidence and uncertainty

Every displayed indicator must identify its derivation, rule version, quality flag, and source evidence IDs. Factual statements in future briefs require a source locator. The original source remains separate from extracted facts. Missing or contradictory inputs route to `insufficient_information` for human review; they must not be silently treated as negative or positive fraud evidence. A synthetic generator label is not independently confirmed fraud.

## Data handling and retention

Use pseudonymous synthetic IDs and synthetic documents only. Do not ingest real claimant, policyholder, police, social media, or identity data. Local raw datasets and SQLite databases belong under ignored `data/` and `artifacts/`; do not commit them or include their contents in logs or screenshots. Retain generated demo cases only as long as needed for local evaluation, then delete local copies. A later operational retention schedule requires a separate data governance decision.

## Trust boundaries and release

Intake forms and documents are untrusted data. Extraction and models may suggest facts or signals but cannot execute reviewer actions. Typed contracts and explicit allowlists must guard every transition and tool call. Bind future services to localhost by default. Before use with real claims, obtain separate data rights, security/privacy review, insurer-specific validation, jurisdiction review, and operational monitoring approval.
