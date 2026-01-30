# BS-AP-SUBLEDGER-RECONCILES — Aged Payables Detail reconciles to Balance Sheet

## Best Practice Reference
Accounts Payable/Receivable

## Why it matters
The AP subledger (aging reports) should reconcile to the Balance Sheet at period end. Differences may indicate
posting errors, missing bills, or report discrepancies.

## Sources & required data
Required:
- QBO Balance Sheet snapshot as-of `period_end` (include “Total Accounts Payable” line when possible)
- AP aging summary total as-of `period_end`
- AP aging detail total as-of `period_end`

## Config parameters
Config model: `ApSubledgerReconcilesRuleConfig`
- `enabled`
- `account_refs` (optional) — list of QBO Balance Sheet account refs to include in AP total
- `account_name_match` (default `accounts payable`) — substring used for name inference
- `allow_name_inference` (default true)
- `summary_evidence_type` (default `ap_aging_summary_total`)
- `detail_evidence_type` (default `ap_aging_detail_total`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `amount_quantize` (optional)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Build AP Balance Sheet total:
   - If a “Total Accounts Payable” line exists → use it
   - Else if `account_refs` provided → sum those balances
   - Else if `allow_name_inference` → sum accounts whose name contains `account_name_match` or `A/P`
3. If no matching accounts → `NOT_APPLICABLE`
4. If any configured `account_refs` are missing → `NEEDS_REVIEW`
5. If summary/detail totals missing → `NEEDS_REVIEW`
6. If summary/detail `as_of_date` missing or not equal to `period_end` → `NEEDS_REVIEW`
7. Compare BS total to both summary and detail totals:
   - If both match exactly → `PASS`
   - If either mismatches → `FAIL`

## Outputs
- `details[]` includes per-account balances and the compared totals/differences
- `human_action` requests reconciliation when not PASS
