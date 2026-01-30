# BS-PLOOTO-CLEARING-ZERO — Plooto Clearing should be zero at period end

## Intent
Ensure the Plooto Clearing control account is exactly zero as of period end.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact zero is expected after quantization)

## Config (knobs)
Config model: `PlootoClearingZeroRuleConfig`
- `enabled`
- `account_ref` (optional) — QBO Balance Sheet account representing Plooto Clearing
- `account_name` (optional label)
- `account_name_match` (default `Plooto Clearing`) — used for name inference when `account_ref` is not configured
- `allow_name_inference` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Decision table
- NOT_APPLICABLE: `enabled == false` OR no matching account found when using name inference
- `missing_data_policy`:
  - `account_ref` configured but account not found in Balance Sheet snapshot
- FAIL:
  - any matching account balance is non-zero
- PASS:
  - all matching account balances are zero

## Edge cases
- If multiple Plooto Clearing accounts exist (e.g., multiple currencies), each is evaluated independently.
- If `amount_quantize` is set (e.g., cents), balances are quantized before comparison.

## Output expectations
- One `details[]` entry per matching account with:
  - `balance`, `inferred_by_name_match`
- `human_action` set for FAIL to prompt clearing any non-zero balance.

## Tests
- `src/backend/tests/rules_engine/test_bs_plooto_clearing_zero.py`
