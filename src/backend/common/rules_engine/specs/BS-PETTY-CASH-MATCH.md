# BS-PETTY-CASH-MATCH — Petty cash matches between QBO Balance Sheet and supporting document

## Intent
Petty cash on the Balance Sheet should match the client’s petty cash supporting documentation at period end.

## Inputs (required)
- `BalanceSheetSnapshot` at `period_end` for the configured petty cash account
- Evidence: an `EvidenceItem` with `evidence_type="petty_cash_support"` (or configured override) and an `amount`
- `ClientRulesConfig` for this rule

## Config (knobs)
Config model: `PettyCashMatchRuleConfig`
- `enabled`
- `account_ref` (required)
- `evidence_type` (default `petty_cash_support`)
- `missing_data_policy` (unused; account missing is treated as NOT_APPLICABLE)

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - `account_ref` not configured, **or**
  - evidence missing/amount missing
- NOT_APPLICABLE:
  - petty cash account missing in QBO/Balance Sheet snapshot
- PASS: `abs(bs_balance - support_amount) == 0`
- FAIL: `abs(bs_balance - support_amount) > 0`

## Edge cases
- Missing evidence never yields FAIL; it yields `NEEDS_REVIEW` by policy.

## Output expectations
- `details[]` includes `bs_balance`, `support_amount`, `difference`.
- `evidence_used[]` includes the evidence item (when present).
- `human_action` set for FAIL/NEEDS_REVIEW.

## Tests
- `src/backend/tests/rules_engine/test_bs_petty_cash_match.py`
