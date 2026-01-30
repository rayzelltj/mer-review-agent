# BS-INVESTMENT-BALANCE-MATCH — Investment balance tallied to statement

## Best Practice Reference
“Loans/investments schedules or statements should be available for all formal loans and investments and these accounts should then be reconciled monthly”

## Why it matters
Investment balances should be reconciled to bank/broker statements so the Balance Sheet reflects the same basis
and period-end value supported by external documentation.

## Sources & required data
Required:
- QBO Balance Sheet snapshot as-of `period_end`
- Investment statement closing balance as-of `period_end` (from Google Drive / broker statement)

## Config parameters
Config model: `InvestmentBalanceMatchRuleConfig`
- `enabled`
- `account_ref` (optional) — QBO Balance Sheet investment account
- `account_name` (optional label)
- `account_name_match` (default `investment`) — substring used for name inference when `account_ref` is not configured
- `allow_name_inference` (default true)
- `evidence_type` (default `investment_statement_balance`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `amount_quantize` (optional)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine the investment account:
   - If `account_ref` configured → use it
   - Else if `allow_name_inference` and `account_name_match` provided → match accounts by name
3. If no matching account → `NOT_APPLICABLE`
4. If multiple matching accounts → `NEEDS_REVIEW`
5. If evidence missing → `NEEDS_REVIEW`
6. If evidence `as_of_date` missing or not equal to `period_end` → `NEEDS_REVIEW`
7. Compare QBO balance to statement balance:
   - If exact match → `PASS`
   - If mismatch → `FAIL`

## Outputs
- `details[]` includes BS balance, statement balance, difference, and evidence metadata
- `human_action` requests statement or reconciliation for non-PASS outcomes

Notes:
- Name inference uses a case-insensitive substring match.
