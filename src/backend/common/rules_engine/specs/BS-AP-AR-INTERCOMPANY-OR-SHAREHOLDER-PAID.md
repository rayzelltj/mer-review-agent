# BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID — Intercompany/shareholder-paid balances identified

## Intent
Identify intercompany-related AP/AR balances and validate that counterpart Balance Sheet balances match in absolute value.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `EvidenceBundle` containing counterparty Balance Sheet balances
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `ApArIntercompanyOrShareholderPaidRuleConfig`
- `enabled`
- `name_patterns` (default: `due to`, `due from`, `intercompany`, `inter-company`)
- `non_zero_only` (default true)
- `evidence_type` (default `intercompany_balance_sheet`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`
- NOT_APPLICABLE:
  - no intercompany accounts found
- PASS:
  - all intercompany balances match counterpart Balance Sheets (absolute value)
- NEEDS_REVIEW:
  - evidence missing, **or**
  - evidence date mismatch, **or**
  - missing/mismatched counterparty balance

## Output expectations
- `details[]` includes per-account comparisons and mismatch summary
- `human_action` set when mismatches exist

## Tests
- `src/backend/tests/rules_engine/test_bs_ap_ar_intercompany_or_shareholder_paid.py`
