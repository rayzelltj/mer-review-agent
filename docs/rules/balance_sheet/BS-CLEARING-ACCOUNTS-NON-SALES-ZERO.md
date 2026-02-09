# BS-CLEARING-ACCOUNTS-NON-SALES-ZERO — Non-sales clearing accounts should be zero at period end

## Best Practice Reference
Clearing accounts (non-sales)

## Why it matters
Clearing accounts outside Current Assets should clear to $0 at month end. Non-zero balances usually indicate
misclassifications or items that should be reclassed to the correct balance sheet account.

## Sources & required data
- QBO Balance Sheet snapshot as-of `period_end`
  - `account_ref`, `name`, `balance`, `type`
- `period_end` date

## Config parameters
Config model: `NonSalesClearingAccountsZeroRuleConfig` (`common.rules_engine.config`)
- `enabled` (bool)
- `name_patterns` (list, default: `["clearing"]`)
- `current_asset_types` (list) — types treated as sales clearing and excluded from this rule
- `missing_data_policy` — when a clearing account lacks account type data
  - `NEEDS_REVIEW` (default) or `NOT_APPLICABLE`
- `amount_quantize` (optional) — Decimal quantization for comparisons (e.g. `"0.01"` for cents)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Find all Balance Sheet accounts whose `name` contains any `name_patterns`
3. Classify as non-sales when `type` is **not** in `current_asset_types`
4. If any clearing accounts are missing `type` → `missing_data_policy`
5. If no non-sales clearing accounts → `NOT_APPLICABLE`
6. For each non-sales clearing account:
   - If `balance == 0` → PASS (per-account)
   - Else → FAIL (per-account)
7. Overall status is the “worst” across accounts: FAIL > NEEDS_REVIEW > PASS > NOT_APPLICABLE

## Outputs
- `status`: PASS / FAIL / NEEDS_REVIEW / NOT_APPLICABLE
- `summary`: includes `period_end` and whether any non-sales clearing accounts are non-zero
- `details[]` for each evaluated account, including `account_name`, `account_type`, `balance`, and per-account `status`

## Related rules
- Sales clearing accounts (Current Assets) are evaluated by `BS-CLEARING-ACCOUNTS-ZERO`.
