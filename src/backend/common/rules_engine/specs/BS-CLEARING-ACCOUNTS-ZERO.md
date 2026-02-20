# BS-CLEARING-ACCOUNTS-ZERO — Sales clearing accounts should be within threshold at period end

## Intent
Any Balance Sheet account under assets whose name contains `clearing` is treated as a sales clearing account.  
The account should clear to zero, with a bounded variance tied to platform revenue and prior-month variance.

## Inputs (required)
- `BalanceSheetSnapshot` at `period_end`
  - account `account_ref`, `name`, `type`, `balance`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `ProfitAndLossSnapshot` with platform revenue lines (`totals["income_line:*"]`)
- `prior_balance_sheets` in `RuleContext`
  - latest snapshot before `period_end` is used for prior-month variance value

## Config (knobs)
Config model: `ClearingAccountsZeroRuleConfig`
- `enabled` (default true)
- `accounts[]` (optional explicit account refs)
- `current_asset_types` (asset classifications eligible for this rule)
- `missing_data_policy` (`NEEDS_REVIEW` or `NOT_APPLICABLE`)

When `accounts[]` is empty, accounts are inferred by name match (`"clearing"`) and asset classification.

## Decision table
- `NOT_APPLICABLE`
  - `enabled == false`, or no eligible sales clearing accounts found
- `NEEDS_REVIEW`
  - account missing from Balance Sheet and `missing_data_policy == NEEDS_REVIEW`
  - clearing account has missing account type/subtype (cannot classify under assets)
  - account name is generic (no platform token), e.g. `Clearing Account`
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

## Naming requirement
Sales clearing account names must include the associated sales platform/channel (e.g. `Etsy Clearing Account`).  
Generic names trigger `NEEDS_REVIEW` with explicit review comment.

## Output expectations
- One `details[]` row per evaluated account including:
  - `platform_revenue`, `previous_month_variance_value`, component rates/amounts
  - `allowed_variance`
  - `allowed_variance_calculation` (numeric formula trace)
  - naming/mapping review flags and comment

## Tests
- `src/backend/tests/rules_engine/test_bs_clearing_accounts_zero.py`
