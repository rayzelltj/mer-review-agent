# BS-BALANCE-UNCHANGED-PRIOR-MONTH — Balances unchanged vs prior month

## Intent
Flag Balance Sheet accounts whose current balance is unchanged compared with the prior month.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- Prior month `BalanceSheetSnapshot` (most recent prior period)
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match after quantization)

## Config (knobs)
Config model: `BalanceUnchangedPriorMonthRuleConfig`
- `enabled`
- `include_zero_balances` (default true)
- `amount_quantize` (optional)

## Decision table
- PASS:
  - no unchanged balances detected
- WARN:
  - one or more leaf account balances equal the prior month balance
- NEEDS_REVIEW:
  - (not used)
- NOT_APPLICABLE:
  - `enabled == false`, **or**
  - prior month snapshot missing

## Edge cases
- Ignores non-leaf rows whose `account_ref` starts with `report::`.
- If `include_zero_balances == false`, zero-balance matches are ignored.

## Output expectations
- `RuleResult.status`: `WARN` when any unchanged balances are found, otherwise `PASS` or `NOT_APPLICABLE`.
- `RuleResult.details`: one entry per unchanged account with current/prior balances.
- `RuleResult.human_action`: prompt to confirm unchanged balances are expected.

## Tests
- Add to `src/backend/tests/rules_engine/` (pending).
