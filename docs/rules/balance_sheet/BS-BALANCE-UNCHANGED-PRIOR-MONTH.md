# BS-BALANCE-UNCHANGED-PRIOR-MONTH — Balances unchanged vs prior month

## Best Practice Reference
Significant balances should be reviewed monthly; unchanged balances can indicate missed updates.

## Why it matters
When a balance does not change month-over-month, it can signal a missed reconciliation,
missing activity, or an account that should be updated monthly but was not.

## Sources & required data
Required:
- QBO Balance Sheet snapshot as-of `period_end`
- Prior month Balance Sheet snapshot (most recent prior period)

## Config parameters
Config model: `BalanceUnchangedPriorMonthRuleConfig`
- `enabled`
- `include_zero_balances` (default true)
- `amount_quantize` (optional)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If prior month snapshot missing → `NOT_APPLICABLE`
3. For each leaf account row (excludes `report::` rows):
   - Compare current vs prior balance (after `amount_quantize`)
   - If equal → flag as `WARN` with message “SAME (unchanged vs prior month).”
4. If no unchanged balances → `PASS`

## Outputs
- `details[]` per unchanged account with current and prior balances
- `human_action` asks reviewer to confirm unchanged balances are expected

Notes:
- This rule uses only the most recent prior month snapshot.
