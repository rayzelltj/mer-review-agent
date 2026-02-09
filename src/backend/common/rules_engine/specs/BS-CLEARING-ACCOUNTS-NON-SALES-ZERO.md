# BS-CLEARING-ACCOUNTS-NON-SALES-ZERO — Non-sales clearing accounts should be zero at period end

## Intent
Non-sales clearing accounts (clearing accounts outside Current Assets) should be exactly $0 at the MER period end.

## Inputs (required)
- `BalanceSheetSnapshot` at `period_end`
  - for each clearing account: `account_ref`, `name`, `balance`, `type`
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `NonSalesClearingAccountsZeroRuleConfig`
- `enabled` (default true)
- `name_patterns` (default: `["clearing"]`)
- `current_asset_types` (defaults to Bank, Accounts Receivable, Other Current Asset, Cash and Cash Equivalents)
- `missing_data_policy` (default `NEEDS_REVIEW`) when a clearing account lacks type data
- `amount_quantize` (optional) for exact matching (typically unset)

## Decision table
- NOT_APPLICABLE: `enabled == false` or no clearing accounts found
- NEEDS_REVIEW:
  - one or more clearing accounts missing account type data (cannot classify sales vs non-sales)
- PASS: all non-sales clearing accounts have `balance == 0`
- FAIL: any non-sales clearing account has `balance != 0`

## Notes
- Sales clearing accounts (current assets) are handled by `BS-CLEARING-ACCOUNTS-ZERO`.
