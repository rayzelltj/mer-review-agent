# BS-CLEARING-ACCOUNTS-ZERO — Sales clearing accounts should be within tolerance at period end

## Intent
Sales clearing accounts (typically in Current Assets) should “wash out” to $0 at the MER period end, or stay within
an allowed variance tied to platform sales. Non-zero balances require explanation or correction.

## Inputs (required)
- `BalanceSheetSnapshot` at `period_end`
  - for each configured clearing account: `account_ref`, `balance`
- `ClientRulesConfig` for this rule
  - list of clearing accounts to evaluate

## Inputs (optional)
- `ProfitAndLossSnapshot` revenue total (`totals["revenue"]`)
  - used only if you configure `% of revenue` tolerances

## Config (knobs)
Config model: `ClearingAccountsZeroRuleConfig`
- `enabled` (default true)
- `accounts[]`: the clearing accounts to evaluate (stable `account_ref`s)
- `current_asset_types`: account types treated as sales clearing (defaults to Bank, Accounts Receivable, Other Current Asset, Cash and Cash Equivalents)
- `default_threshold` and per-account `threshold`:
  - `floor_amount` (absolute tolerance)
  - `pct_of_revenue` (e.g. `0.001` = 0.1% of revenue)
- `missing_data_policy`: what to do if an expected account is missing in the snapshot (`NEEDS_REVIEW` or `NOT_APPLICABLE`)

### Fallback (when not configured)
If `accounts[]` is empty/missing, the rule falls back to evaluating Balance Sheet accounts whose `name`
contains `"clearing"` (case-insensitive) **and** whose account type is one of `current_asset_types`.

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - one or more configured accounts missing from the Balance Sheet and `missing_data_policy == NEEDS_REVIEW`
  - one or more clearing accounts lack account type data (cannot classify sales vs non-sales)
- PASS: all sales clearing accounts have `abs(balance) == 0`
- WARN: at least one configured clearing account has `0 < abs(balance) <= allowed_variance`, and none exceed allowed variance
- FAIL: at least one configured clearing account has `abs(balance) > allowed_variance`

Where:
- `allowed_variance = max(floor_amount, abs(revenue_total) * pct_of_revenue)`
- if revenue is missing → the revenue component is treated as `0`, so `allowed_variance = floor_amount`

## Edge cases
- Missing `ProfitAndLossSnapshot` or missing `totals["revenue"]` → tolerance becomes floor-only.
- Negative balances are evaluated using `abs(balance)`.
- Non-sales clearing accounts are handled by `BS-CLEARING-ACCOUNTS-NON-SALES-ZERO`.

## Output expectations
- One `RuleResult.details[]` entry per configured account, including:
  - `balance`, `allowed_variance`, threshold values, and per-account status
- `human_action` is set for `WARN`, `FAIL`, and `NEEDS_REVIEW`.

## Tests
- `src/backend/tests/rules_engine/test_bs_clearing_accounts_zero.py`
- Covered cases: PASS, WARN, FAIL, missing-account → NEEDS_REVIEW
