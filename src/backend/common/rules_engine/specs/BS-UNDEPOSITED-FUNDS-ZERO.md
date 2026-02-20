# BS-UNDEPOSITED-FUNDS-ZERO — Undeposited Funds should be zero at period end

## Intent
Undeposited accounts under assets should clear to $0 at period end.  
This rule uses the same variance logic as sales clearing accounts, with account discovery based on `undeposited`.

## Inputs (required)
- `BalanceSheetSnapshot` at `period_end`
  - account `account_ref`, `name`, `type`, `balance`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `ProfitAndLossSnapshot` with platform revenue lines (`totals["income_line:*"]`)
- `prior_balance_sheets` in `RuleContext`
  - latest snapshot before `period_end` is used for prior-month variance value

## Config (knobs)
Config model: `ZeroBalanceRuleConfig`
- `enabled` (default true)
- `accounts[]` (optional explicit account refs)
- `missing_data_policy` (`NEEDS_REVIEW` or `NOT_APPLICABLE`)

When `accounts[]` is empty, accounts are inferred by name match (`"undeposited"`) and asset classification.

## Decision table
- `NOT_APPLICABLE`
  - `enabled == false`, or no eligible undeposited accounts found
- `NEEDS_REVIEW`
  - account missing from Balance Sheet and `missing_data_policy == NEEDS_REVIEW`
  - undeposited account has missing account type/subtype (cannot classify under assets)
  - account name is generic (no platform token), e.g. `Undeposited Funds`
  - platform revenue mapping not found in P&L (`income_line:*`)
- `PASS`
  - all evaluated accounts have `abs(balance) == 0` and naming/mapping checks pass
- `WARN`
  - at least one account has `0 < abs(balance) <= allowed_variance`, none exceed
- `FAIL`
  - at least one account has `abs(balance) > allowed_variance`

## Allowed variance formula
`allowed_variance = (10% * abs(platform_revenue)) + (3% * abs(previous_month_variance_value))`

Where:
- `platform_revenue` is summed from matched `income_line:*` P&L rows based on account-name tokens.
- `previous_month_variance_value` is the latest prior-period absolute balance for the same account ref.
- If prior snapshot/account is missing, prior-month component defaults to `0` and is flagged in detail payload.

## Edge cases
- If account names do not include platform-identifying terms (for example only `Undeposited Funds`), the rule returns `NEEDS_REVIEW`.
- Negative balances are evaluated via `abs(balance)`.

## Output expectations
- One `details[]` row per evaluated account including:
  - `platform_revenue`, `previous_month_variance_value`, component rates/amounts
  - `allowed_variance`
  - `allowed_variance_calculation` (numeric formula trace)
  - naming/mapping review flags and comment

## Tests
- `src/backend/tests/rules_engine/test_bs_undeposited_funds_zero.py`
