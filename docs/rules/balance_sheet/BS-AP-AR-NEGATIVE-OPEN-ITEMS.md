# BS-AP-AR-NEGATIVE-OPEN-ITEMS — Negative open items identified

## Best Practice Reference
Accounts Payable/Receivable

## Why it matters
Negative open balances in AP/AR aging detail typically represent credits or overpayments that should be reviewed
and justified.

## Sources & required data
Required:
- QBO A/P Aging Detail report as-of `period_end`
- QBO A/R Aging Detail report as-of `period_end`

## Config parameters
Config model: `ApArNegativeOpenItemsRuleConfig`
- `enabled`
- `ap_detail_rows_evidence_type` (default `ap_aging_detail_rows`)
- `ar_detail_rows_evidence_type` (default `ar_aging_detail_rows`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Evidence item shape (required fields)
Each detail evidence item must include:
- `amount` (overall total, not used in the check)
- `as_of_date`
- `meta.items[]` with:
  - `name`
  - `open_balance` (negative values are flagged)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If AP/AR detail evidence missing → `missing_data_policy`
3. If evidence `as_of_date` missing or not equal to `period_end` → `missing_data_policy`
4. Flag any AP or AR item where `open_balance < 0` → `NEEDS_REVIEW`
5. If no negatives → `PASS`

## Outputs
- `details[]` includes negative items (sample) for AP and AR
- `human_action` requests justification when negatives exist
