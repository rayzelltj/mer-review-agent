# BS-BANK-RECONCILED-THROUGH-PERIOD-END — Bank/credit card accounts reconciled through statement date

## Intent
For each bank/credit card account, confirm reconciliation coverage through MER period end and confirm the book/register balance ties to the statement ending balance (exact match).

This rule is **adapter-friendly**: it evaluates `ReconciliationSnapshot`s and does not depend on QBO’s reconciliation report API.

## Inputs (required)
- `RuleContext.period_end`
- `RuleContext.reconciliations[]` (`ReconciliationSnapshot`) containing, per account:
  - `statement_end_date`
  - `statement_ending_balance`
  - `book_balance_as_of_statement_end`
- `BalanceSheetSnapshot` at `period_end` to determine which accounts must be covered
- `ClientRulesConfig` for this rule

## Inputs (optional)
None (tie-out is exact match; optional quantization may be configured)

## Config (knobs)
Config model: `BankReconciledThroughPeriodEndRuleConfig`
- `enabled`
- `expected_accounts[]` (required; sourced from client maintenance bank/cc list)
  - missing any expected account snapshot triggers `missing_data_policy`
- `require_statement_end_date_gte_period_end` (default true)
  - if true, any snapshot with `statement_end_date < period_end` fails
- `require_statement_balance_matches_attachment` (default true)
  - if true, requires a statement artifact evidence item and compares it to `statement_ending_balance` (exact match)
- `statement_balance_attachment_evidence_type` (default `statement_balance_attachment`)
- `require_statement_balance_matches_balance_sheet` (default true)
- `require_book_balance_as_of_period_end_ties_to_balance_sheet` (default true)
- `missing_data_policy`

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - no reconciliation snapshots provided, **or**
  - expected account snapshot missing (when `expected_accounts` configured), **or**
  - per-snapshot required fields missing and `missing_data_policy == NEEDS_REVIEW`
- FAIL (coverage): `require_statement_end_date_gte_period_end == true` AND `statement_end_date < period_end`
- PASS/FAIL (tie-out):
  - PASS: `abs(book_balance_as_of_statement_end - statement_ending_balance) == 0`
  - FAIL: `diff > 0`
- PASS/FAIL (attachment, optional):
  - PASS: evidence amount equals `statement_ending_balance` (and evidence `statement_end_date` matches when provided)
  - FAIL: mismatch
  - NEEDS_REVIEW: evidence missing and `missing_data_policy == NEEDS_REVIEW`

Overall status is the worst across evaluated snapshots.

## Edge cases
- Scope is driven by `expected_accounts[]` (client maintenance), not by Balance Sheet type/subtype inference.

## Output expectations
- One `details[]` entry per reconciliation snapshot evaluated.
- `human_action` set for FAIL/NEEDS_REVIEW.

## Tests
- `src/backend/tests/rules_engine/test_bs_bank_reconciled_through_period_end.py`
