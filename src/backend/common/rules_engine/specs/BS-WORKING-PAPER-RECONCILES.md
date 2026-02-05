# BS-WORKING-PAPER-RECONCILES — Working papers reconcile to Balance Sheet

## Intent
Ensure Balance Sheet accounts supported by working papers (prepaids, deferred revenue, accruals)
reconcile to the schedules at period end.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot`
- `EvidenceBundle` containing working paper balances
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `WorkingPaperReconcilesRuleConfig`
- `enabled`
- `evidence_type` (default `working_paper_balance`)
- `name_patterns` (default `prepaid`, `deferred revenue`, `accrual`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `amount_quantize` (optional)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, or
  - no in-scope Balance Sheet accounts
- NEEDS_REVIEW:
  - working paper evidence missing, or
  - evidence `as_of_date` missing or does not match `period_end`
- FAIL:
  - any in-scope account does not match its working paper balance (exact match)
- PASS:
  - all in-scope accounts match working paper balances

## Output expectations
- `details[]` includes per-account comparison
- `human_action` set when mismatches occur

## Tests
- `src/backend/tests/rules_engine/test_bs_working_paper_reconciles.py`
