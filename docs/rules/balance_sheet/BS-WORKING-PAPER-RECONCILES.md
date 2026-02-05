# BS-WORKING-PAPER-RECONCILES — Working papers reconcile to Balance Sheet

## Best Practice Reference
Prepayments/Deferred Revenue/Accruals

## Why it matters
Balance Sheet lines supported by working papers (prepaids, deferred revenue, accruals) should reconcile
to the underlying schedules each month-end.

## Sources & required data
Required:
- Balance Sheet snapshot as-of `period_end`
- Working paper balance evidence (e.g., Prepaid Schedule)

## Config parameters
Config model: `WorkingPaperReconcilesRuleConfig`
- `enabled`
- `evidence_type` (default `working_paper_balance`)
- `name_patterns` (default `prepaid`, `deferred revenue`, `accrual`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `amount_quantize` (optional, for cents)

## Evidence item shape (required fields)
Each working paper evidence item must include:
- `amount`
- `as_of_date`
- optional `uri` (future MER link)
- optional `meta.account_name_match` for multi-account mapping

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Find in-scope Balance Sheet accounts by `name_patterns`
3. If none found → `NOT_APPLICABLE`
4. If evidence missing → `NEEDS_REVIEW`
5. If evidence `as_of_date` missing or not equal to `period_end` → `NEEDS_REVIEW`
6. Compare Balance Sheet vs working paper amounts (exact match)
7. Any mismatch → `FAIL`; otherwise `PASS`

## Outputs
- `details[]` includes per-account balances, differences, and the working paper link (if provided)
- `human_action` set when mismatches occur
