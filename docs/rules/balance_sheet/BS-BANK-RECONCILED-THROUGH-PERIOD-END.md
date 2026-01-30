# BS-BANK-RECONCILED-THROUGH-PERIOD-END — Bank/credit card accounts reconciled through statement date

## Best Practice Reference
Bank reconciliations → Banks and Credit cards

## Why it matters
If bank/credit card accounts are not reconciled through month end **or** reconciliation balances do not agree to bank statements/activity statements, cash and liabilities may be materially misstated and downstream tie-outs (cash rollforward, AR/AP) become unreliable.

## Sources & required data
Current implementation is adapter-friendly and uses structured reconciliation snapshots (not a QBO “reconciliation report” API).

Required:
- QBO Balance Sheet snapshot as-of `period_end` to infer bank/cc accounts in-scope (by `type`/`subtype`)
- `ReconciliationSnapshot[]` for each in-scope account
- Bank statement/activity statement evidence per account (ending balance)
- `period_end` date

Optional:
None (statement attachments are required for this rule)

## Config parameters
Config model: `BankReconciledThroughPeriodEndRuleConfig`
- `enabled`
- `include_accounts[]` / `exclude_accounts[]` (optional overrides)
  - Include/exclude specific accounts from the inferred bank/cc scope
- `expected_accounts[]` (maintenance list for count comparison)
  - Compared to inferred bank/cc count; mismatch → FAIL
- `require_statement_end_date_gte_period_end` (default true)
  - If true, `statement_end_date < period_end` → FAIL
- `statement_balance_attachment_evidence_type` (default `statement_balance_attachment`)
  - Evidence must include `meta.account_ref` and `amount`; optionally `statement_end_date` (if provided and differs → FAIL)
- `require_statement_balance_matches_balance_sheet` (optional cross-check)
- `missing_data_policy` (default NEEDS_REVIEW)
- `amount_quantize` (optional)
- Severity (fixed mapping from status): PASS INFO / WARN LOW / FAIL HIGH / NEEDS_REVIEW MED / NOT_APPLICABLE INFO

### Business-intent gaps (TBD)
None (current implementation enforces attachment tie-out, register balance vs Balance Sheet, and maintenance count check).

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine required account refs:
   - Default: infer bank/cc scope from Balance Sheet `type`/`subtype`
     - If `type`/`subtype` are missing → `NEEDS_REVIEW` (do not guess by name)
   - Apply overrides:
     - include `include_accounts[]`
     - exclude `exclude_accounts[]`
   - Back-compat: if `expected_accounts[]` is provided, use it as the explicit list (skip inference)
3. Count check:
   - If `expected_accounts[]` is provided, compare its count to inferred bank/cc count → mismatch = FAIL
4. For each required account:
   - If no reconciliation snapshot found → `missing_data_policy`
   - Select the latest snapshot by `statement_end_date`
   - Coverage check (if enabled): if `statement_end_date < period_end` → FAIL
   - Statement tie-out:
     - missing required fields → `missing_data_policy`
     - else compare `book_balance_as_of_statement_end` vs `statement_ending_balance`:
       - diff == 0 → PASS
       - diff > 0 → FAIL
   - **Required** attachment check:
     - require evidence item `statement_balance_attachment_evidence_type` where `meta.account_ref` matches the account
     - compare evidence `amount` to `statement_ending_balance` (exact match)
   - **Required** period-end tie-out:
     - compare `book_balance_as_of_period_end` vs Balance Sheet account balance (exact match)
   - Optional Balance Sheet match (if enabled):
     - compare reconciliation `statement_ending_balance` to Balance Sheet account balance (exact match)
4. Overall status is the worst across accounts

## Outputs
- `details[]` (one per required account) includes:
  - `account_name`, `period_end`, `statement_end_date`
  - statement tie fields: balances, diff, per-check status
  - attachment fields: evidence type, amount, diff, per-check status
  - period-end tie fields: balances, diff, per-check status
  - overall per-account status
- If a maintenance list is provided, an extra `details[]` entry (`key="scope_count"`) records the count comparison.

## Edge cases
- Multiple reconciliation snapshots per account: latest `statement_end_date` wins
- Amount rounding: only applied when `amount_quantize` is set

## Test matrix
| Scenario | Expected |
|---|---|
| Statement end >= period end, ties out | PASS / INFO |
| Statement end < period end | FAIL / HIGH |
| Missing reconciliation snapshot | NEEDS_REVIEW (or NOT_APPLICABLE if configured) |
| Missing statement/book fields | NEEDS_REVIEW |
| Types missing and no expected list | NEEDS_REVIEW |
| Period-end tie-out enabled and mismatched | FAIL / HIGH |
