# BS-AP-AR-NEGATIVE-OPEN-ITEMS — Negative open items identified

## Intent
Identify negative open balances in AP/AR aging detail reports (credits/overpayments).

## Inputs (required)
- `RuleContext.period_end`
- `EvidenceBundle` containing AP and AR aging detail rows
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `ApArNegativeOpenItemsRuleConfig`
- `enabled`
- `ap_detail_rows_evidence_type` (default `ap_aging_detail_rows`)
- `ar_detail_rows_evidence_type` (default `ar_aging_detail_rows`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`
- `missing_data_policy`:
  - AP or AR detail evidence missing, **or**
  - evidence `as_of_date` missing or not equal to `period_end`, **or**
  - detail items missing
- NEEDS_REVIEW:
  - any AP or AR detail row has `open_balance < 0`
- PASS:
  - no negative open balances

## Output expectations
- `details[]` includes negative item samples for AP and AR
- `human_action` set when negatives exist

## Tests
- `src/backend/tests/rules_engine/test_bs_ap_ar_negative_open_items.py`
