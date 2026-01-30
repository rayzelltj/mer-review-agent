# BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS — AP/AR items older than 60 days flagged

## Best Practice Reference
Accounts Payable/Receivable

## Why it matters
Open bills/invoices older than 60 days indicate collection/payment issues and require review. Discrepancies between
AP/AR summary and detail aging reports should also be flagged.

## Sources & required data
Required (QBO aging reports; no Balance Sheet needed):
- AP aging summary total for items > 60 days
- AP aging detail report (item-level) for items > 60 days
- AR aging summary total for items > 60 days
- AR aging detail report (item-level) for items > 60 days

## Config parameters
Config model: `ApArItemsOlderThan60DaysRuleConfig`
- `enabled`
- `age_threshold_days` (default `60`)
- `ap_summary_evidence_type` (default `ap_aging_summary_over_60`)
- `ap_detail_evidence_type` (default `ap_aging_detail_over_60`)
- `ar_summary_evidence_type` (default `ar_aging_summary_over_60`)
- `ar_detail_evidence_type` (default `ar_aging_detail_over_60`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)
- `amount_quantize` (optional)

## Evidence item shape (required fields)
Each evidence item must include:
- `amount` → total amount for items older than threshold
- `as_of_date`
- `meta.items[]` → list of items:
  - Detail items: `name`, `amount`, and either `txn_date` (ISO date) **or** `age_bucket`/`days_past_due`
  - Summary items: `name`, `amount` (totals for items older than threshold)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If any AP/AR summary or detail evidence missing → `missing_data_policy`
3. If any evidence `as_of_date` missing or not equal to `period_end` → `missing_data_policy`
4. Identify detail items with `txn_date < period_end - age_threshold_days`
5. If any items older than threshold → `NEEDS_REVIEW`
6. Compare summary vs detail by `name` for items older than threshold:
   - If any discrepancy → `NEEDS_REVIEW`
7. If no items older than threshold and no discrepancies → `PASS`

## Outputs
- `details[]` includes:
  - over-threshold items (sample)
  - totals from detail vs summary
  - discrepancy list when present
