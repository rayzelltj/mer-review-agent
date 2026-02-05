# BS-INTERCOMPANY-BALANCES-RECONCILE — Intercompany loan balances reconcile

## Intent
Ensure intercompany loan balances reconcile across related entities using Balance Sheet amounts.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `EvidenceBundle` containing counterpart Balance Sheet balances
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `IntercompanyBalancesReconcileRuleConfig`
- `enabled`
- `name_patterns` (default: `intercompany loan`, `due to`, `due from`, `loan from`, `loan to`, `shareholder loan`)
- `non_zero_only` (default true)
- `evidence_type` (default `intercompany_balance_sheet`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, **or**
  - no intercompany loan accounts found
- NEEDS_REVIEW:
  - evidence missing, **or**
  - evidence date mismatch, **or**
  - missing/mismatched counterparty balance
- PASS:
  - all intercompany loan balances match counterpart Balance Sheets (absolute value)

## Output expectations
- `details[]` includes per-account comparisons and mismatch summary
- `human_action` set when mismatches exist

## Tests
- `src/backend/tests/rules_engine/test_bs_intercompany_balances_reconcile.py`
