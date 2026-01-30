# BS-INVESTMENT-BALANCE-MATCH — Investment balance tallied to statement

## Intent
Ensure the Balance Sheet investment balance matches the closing balance on the investment statement as of period end.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `EvidenceBundle` containing an investment statement balance item as of `period_end`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match is expected after quantization)

## Config (knobs)
Config model: `InvestmentBalanceMatchRuleConfig`
- `enabled`
- `account_ref` (optional)
- `account_name` (optional label)
- `account_name_match` (default `investment`, substring used for name inference)
- `allow_name_inference` (default true)
- `evidence_type` (default `investment_statement_balance`)
- `require_evidence_as_of_date_match_period_end` (default true)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, **or**
  - no matching account found (no `account_ref`, no match by `account_name_match`)
- NEEDS_REVIEW:
  - multiple matching accounts found, **or**
  - evidence missing or evidence `amount` missing, **or**
  - evidence `as_of_date` missing or not equal to `period_end`
- FAIL:
  - `abs(bs_balance - statement_balance) != 0`
- PASS:
  - `bs_balance == statement_balance`

## Edge cases
- If multiple investment accounts match by name, the rule requires a specific `account_ref`.
- If `amount_quantize` is set (e.g., cents), both values are quantized before comparison.

## Output expectations
- One `details[]` entry with:
  - `bs_balance`, `statement_balance`, `difference`
  - evidence metadata (`evidence_type`, `evidence_as_of_date`)
- `human_action` set for FAIL/NEEDS_REVIEW to request statement or reconciliation.

## Tests
- `src/backend/tests/rules_engine/test_bs_investment_balance_match.py`
