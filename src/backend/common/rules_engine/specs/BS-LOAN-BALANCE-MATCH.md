# BS-LOAN-BALANCE-MATCH — Loan balance tallied to loan schedule

## Intent
Ensure the Balance Sheet loan balance matches the outstanding balance in the client’s loan schedule as of period end.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `EvidenceBundle` containing a loan schedule balance item as of `period_end`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match is expected after quantization)

## Config (knobs)
Config model: `LoanBalanceMatchRuleConfig`
- `enabled`
- `account_ref` (optional)
- `account_name` (optional label)
- `account_name_match` (default `loan`, substring used for name inference)
- `allow_name_inference` (default true)
- `evidence_type` (default `loan_schedule_balance`)
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
  - `abs(bs_balance - schedule_balance) != 0`
- PASS:
  - `bs_balance == schedule_balance`

## Edge cases
- If multiple loan accounts match by name, the rule requires a specific `account_ref`.
- If `amount_quantize` is set (e.g., cents), both values are quantized before comparison.

## Output expectations
- One `details[]` entry with:
  - `bs_balance`, `schedule_balance`, `difference`
  - evidence metadata (`evidence_type`, `evidence_as_of_date`)
- `human_action` set for FAIL/NEEDS_REVIEW to request schedule or reconciliation.

## Tests
- `src/backend/tests/rules_engine/test_bs_loan_balance_match.py`
