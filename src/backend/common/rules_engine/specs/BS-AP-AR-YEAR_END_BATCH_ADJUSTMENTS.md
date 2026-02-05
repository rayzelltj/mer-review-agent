# BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS — Year-end batch adjustments not left as generic supplier/customer

## Intent
Identify generic year-end AP/AR batch adjustment names in aging detail reports.

## Inputs (required)
- `RuleContext.period_end`
- `EvidenceBundle` containing AP and AR aging detail rows
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `ApArYearEndBatchAdjustmentsRuleConfig`
- `enabled`
- `ap_detail_rows_evidence_type` (default `ap_aging_detail_rows`)
- `ar_detail_rows_evidence_type` (default `ar_aging_detail_rows`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `name_patterns` (default: `yer supplier`, `year-end review`, `ye adj`, `year end`, `y/e`)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, **or**
  - AP/AR detail evidence missing, **or**
  - evidence `as_of_date` missing or not equal to `period_end`, **or**
  - detail items missing
- NEEDS_REVIEW:
  - any AP/AR detail name matches generic year-end patterns
- PASS:
  - no generic year-end names found

## Output expectations
- `details[]` includes flagged AP and AR names
- `human_action` set when generic names are detected

## Tests
- `src/backend/tests/rules_engine/test_bs_ap_ar_year_end_batch_adjustments.py`
