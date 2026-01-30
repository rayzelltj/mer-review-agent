# BS-BANK-RECONCILED-THROUGH-PERIOD-END — Bank/credit card accounts reconciled through statement date

## Intent
For each bank/credit card account, confirm reconciliation coverage through MER period end, validate the statement ending balance against the bank statement/activity statement, and confirm the register balance as of period end ties to the Balance Sheet (exact match).

This rule is **adapter-friendly**: it evaluates `ReconciliationSnapshot`s and does not depend on QBO’s reconciliation report API.

## Inputs (required)
- `RuleContext.period_end`
- `RuleContext.reconciliations[]` (`ReconciliationSnapshot`) containing, per account:
  - `statement_end_date`
  - `statement_ending_balance`
  - `book_balance_as_of_statement_end`
  - `book_balance_as_of_period_end` (register balance as of period end)
- `BalanceSheetSnapshot` at `period_end` to infer bank/credit card scope (by `type` / `subtype`)
- `EvidenceBundle` with bank statement (or PayPal activity statement) ending balances per account
- `ClientRulesConfig` for this rule (including maintenance list when available)

## Inputs (optional)
None (tie-out is exact match; optional quantization may be configured)

## Config (knobs)
Config model: `BankReconciledThroughPeriodEndRuleConfig`
- `enabled`
- `include_accounts[]` / `exclude_accounts[]` (optional overrides)
  - used to include/exclude specific accounts from the inferred bank/cc scope
- `expected_accounts[]` (maintenance list, used for count comparison)
  - compared to Balance Sheet bank/cc account count; mismatch → FAIL
- `require_statement_end_date_gte_period_end` (default true)
  - if true, any snapshot with `statement_end_date < period_end` fails
- `statement_balance_attachment_evidence_type` (default `statement_balance_attachment`)
- `require_statement_balance_matches_balance_sheet` (optional)
  - optional cross-check (not required by policy)
- `missing_data_policy`

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - no reconciliation snapshots provided, **or**
  - unable to infer bank/cc scope because Balance Sheet account `type`/`subtype` are missing, **or**
  - expected account snapshot missing (when explicitly scoped), **or**
  - required fields missing (statement end date, statement ending balance, register balance as of period end), **or**
  - required bank statement/activity statement evidence missing
- FAIL (coverage): `require_statement_end_date_gte_period_end == true` AND `statement_end_date < period_end`
- FAIL (statement tie-out): `abs(book_balance_as_of_statement_end - statement_ending_balance) > 0`
- FAIL (attachment tie-out): statement ending balance does **not** match attachment ending balance
- FAIL (register vs BS): `abs(book_balance_as_of_period_end - balance_sheet_balance) > 0`
- FAIL (count check): `len(expected_accounts) != inferred_bank_cc_count` (when maintenance list provided)

Overall status is the worst across evaluated snapshots.

## Edge cases
- Default scope is inferred from Balance Sheet account `type` / `subtype`.
- If account `type` / `subtype` are missing, the rule returns `NEEDS_REVIEW` rather than guessing by name.
- Bank statement evidence is required for each account (e.g., PayPal activity statement per currency/account).

## Output expectations
- One `details[]` entry per reconciliation snapshot evaluated.
- If maintenance list provided, an additional `details[]` entry with key `scope_count` documenting count comparison.
- `human_action` set for FAIL/NEEDS_REVIEW.

## Tests
- `src/backend/tests/rules_engine/test_bs_bank_reconciled_through_period_end.py`
