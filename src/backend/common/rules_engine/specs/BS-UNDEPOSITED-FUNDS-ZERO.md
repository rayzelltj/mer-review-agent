# BS-UNDEPOSITED-FUNDS-ZERO — Undeposited Funds should be zero at period end

## Intent
Undeposited Funds should clear to $0 at the MER period end. Non-zero balances require explanation (timing) or investigation.

## Inputs (required)
- `BalanceSheetSnapshot` at `period_end` for the configured Undeposited Funds account(s)
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `ProfitAndLossSnapshot` revenue total (`totals["revenue"]`) for `% of revenue` tolerances

## Config (knobs)
Config model: `ZeroBalanceRuleConfig`
- `enabled`
- `accounts[]` (typically 1 account, but the implementation supports multiple; if empty, names containing `undeposited` are inferred)
- `default_threshold` and per-account `threshold` (`floor_amount`, `pct_of_revenue`)
- `missing_data_policy`

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - no accounts found (configured or inferred), **or**
  - configured account missing and `missing_data_policy == NEEDS_REVIEW`
- PASS: all configured Undeposited Funds accounts have `abs(balance) == 0`
- WARN: at least one has `0 < abs(balance) <= allowed_variance`, and none exceed allowed variance
- FAIL: at least one has `abs(balance) > allowed_variance`

`allowed_variance` is computed the same as the clearing accounts rule.

## Edge cases
- Missing P&L revenue → floor-only tolerance.
- Negative balances evaluated via `abs(balance)`.

## Output expectations
- One `details[]` entry per configured or inferred account.
- `human_action` set for WARN/FAIL/NEEDS_REVIEW.

## Tests
- `src/backend/tests/rules_engine/test_bs_undeposited_funds_zero.py`
