# BS-AP-AR-YEAR_END_BATCH_ADJUSTMENTS — Year-end batch adjustments not left as generic supplier/customer

## Best Practice Reference
Accounts Payable/Receivable → Year End Adjustments

## Why it matters
Year-end batch adjustments should not be posted to generic supplier/customer names without breakdown.
Generic names require review and documentation.

## Sources & required data
Required:
- QBO A/P Aging Detail report as-of `period_end`
- QBO A/R Aging Detail report as-of `period_end`

## Config parameters
Config model: `ApArYearEndBatchAdjustmentsRuleConfig`
- `enabled`
- `ap_detail_rows_evidence_type` (default `ap_aging_detail_rows`)
- `ar_detail_rows_evidence_type` (default `ar_aging_detail_rows`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `name_patterns` (default: `yer supplier`, `year-end review`, `ye adj`, `year end`, `y/e`)
- `missing_data_policy` (unused; missing evidence → `NOT_APPLICABLE`)

## Evidence item shape (required fields)
Each detail evidence item must include:
- `as_of_date`
- `meta.items[]` with:
  - `name` (supplier/customer name)
  - `open_balance`

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If AP/AR detail evidence missing → `NOT_APPLICABLE`
3. If evidence `as_of_date` missing or not equal to `period_end` → `NOT_APPLICABLE`
4. Flag any name matching patterns or starting with `YE`, `Y/E`, or `Year End` → `NEEDS_REVIEW`
5. If no generic names → `PASS`

## Outputs
- `details[]` includes flagged names for AP and AR
- `human_action` requests breakdown and clearing when flagged
