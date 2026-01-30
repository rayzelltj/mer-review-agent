# BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS — AP/AR items older than 60 days flagged

## Intent
Identify AP/AR items older than 60 days and flag discrepancies between aging summary and detail reports.

## Inputs (required)
- `RuleContext.period_end`
- `EvidenceBundle` containing:
  - AP aging summary total (items > threshold)
  - AP aging detail items (all items; rule filters by threshold)
  - AR aging summary total (items > threshold)
  - AR aging detail items (all items; rule filters by threshold)
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match is expected after quantization)

## Config (knobs)
Config model: `ApArItemsOlderThan60DaysRuleConfig`
- `enabled`
- `age_threshold_days` (default `60`)
- `ap_summary_evidence_type` (default `ap_aging_summary_over_60`)
- `ap_detail_evidence_type` (default `ap_aging_detail_over_60`)
- `ar_summary_evidence_type` (default `ar_aging_summary_over_60`)
- `ar_detail_evidence_type` (default `ar_aging_detail_over_60`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`
- `missing_data_policy`:
  - any evidence item missing, **or**
  - evidence `as_of_date` missing or not equal to `period_end`, **or**
  - item-level metadata missing or invalid
- NEEDS_REVIEW:
  - any AP/AR items older than threshold, **or**
  - discrepancies between summary and detail totals by name
- PASS:
  - no items older than threshold **and** no discrepancies

## Edge cases
- If any detail items are missing dates or amounts, the rule returns `missing_data_policy`.
- Detail items may supply `txn_date` or `age_bucket`/`days_past_due` to determine age.
- Summary/detail discrepancies are computed by aggregating detail items by name.

## Output expectations
- `details[]` includes:
  - over-threshold item count and sample
  - summary vs detail totals
  - discrepancy list

## Tests
- `src/backend/tests/rules_engine/test_bs_ap_ar_items_older_than_60_days.py`
