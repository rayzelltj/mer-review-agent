# BS-BANK-RECONCILED-THROUGH-PERIOD-END — Bank/credit card accounts reconciled through statement date

## Best Practice Reference
Bank reconciliations → Banks and Credit cards

## Why it matters
If bank/credit card accounts are not reconciled through month end, cash and liabilities may be materially misstated and downstream tie-outs (cash rollforward, AR/AP) become unreliable.

## Sources & required data
Current implementation is adapter-friendly and uses structured reconciliation snapshots (not a QBO “reconciliation report” API).

Required:
- QBO Balance Sheet snapshot as-of `period_end` to infer bank/cc accounts in-scope (by `type`/`subtype`)
- `ReconciliationSnapshot[]` for each in-scope account, typically derived from:
  - QBO reconciliation exports/reports, plus statement artifacts
- `period_end` date

Optional:
None (statement attachments are required when `require_statement_balance_matches_attachment` is enabled)

## Config parameters
Config model: `BankReconciledThroughPeriodEndRuleConfig`
- `enabled`
- `include_accounts[]` / `exclude_accounts[]` (optional overrides)
  - Include/exclude specific accounts from the inferred bank/cc scope
- `expected_accounts[]` (back-compat explicit list)
  - If provided, treated as an explicit include list (inference is skipped)
- `require_statement_end_date_gte_period_end` (default true)
  - If true, `statement_end_date < period_end` → FAIL
- `require_book_balance_as_of_period_end_ties_to_balance_sheet` (default true)
  - If true, also compares `book_balance_as_of_period_end` vs Balance Sheet account balance
- `require_statement_balance_matches_attachment` (default true)
  - Requires a statement artifact/attachment amount per account and compares it to `statement_ending_balance` (exact match)
- `require_statement_balance_matches_balance_sheet` (default true)
  - Compares reconciliation report `statement_ending_balance` to the Balance Sheet account balance (exact match)
- `statement_balance_attachment_evidence_type` (default `statement_balance_attachment`)
  - Evidence must include `meta.account_ref` and `amount`; optionally `statement_end_date` (if provided and differs → FAIL)
- `missing_data_policy` (default NEEDS_REVIEW)
- `amount_quantize` (optional)
- Severity (fixed mapping from status): PASS INFO / WARN LOW / FAIL HIGH / NEEDS_REVIEW MED / NOT_APPLICABLE INFO

### Business-intent gaps (TBD)
The written intent mentions additional checks that are not fully implemented yet:
1. If a client-maintained “accounts requiring reconciliation” list is required as a control, that needs a separate rule/check.
2. Balance Sheet balance ties to register balance as-of period end via a clarified policy (partial support exists via optional check)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine required account refs:
   - Default: infer bank/cc scope from Balance Sheet `type`/`subtype`
     - If `type`/`subtype` are missing → `NEEDS_REVIEW` (do not guess by name)
   - Apply overrides:
     - include `include_accounts[]`
     - exclude `exclude_accounts[]`
   - Back-compat: if `expected_accounts[]` is provided, use it as the explicit include list (skip inference)
3. For each required account:
   - If no reconciliation snapshot found → `missing_data_policy`
   - Select the latest snapshot by `statement_end_date`
   - Coverage check (if enabled): if `statement_end_date < period_end` → FAIL
   - Statement tie-out:
     - missing required fields → `missing_data_policy`
     - else compare `book_balance_as_of_statement_end` vs `statement_ending_balance`:
       - diff == 0 → PASS
       - diff > 0 → FAIL
   - Optional attachment check (if enabled):
     - require evidence item `statement_balance_attachment_evidence_type` where `meta.account_ref` matches the account
     - compare evidence `amount` to `statement_ending_balance` (exact match)
   - Optional Balance Sheet match (if enabled):
     - compare reconciliation `statement_ending_balance` to Balance Sheet account balance (exact match)
   - Optional period-end tie-out (if enabled):
     - compare `book_balance_as_of_period_end` vs Balance Sheet account balance (exact match)
4. Overall status is the worst across accounts

## Outputs
- `details[]` (one per required account) includes:
  - `account_name`, `period_end`, `statement_end_date`
  - statement tie fields: balances, diff, per-check status
  - attachment fields (when enabled): evidence type, amount, diff, per-check status
  - optional period-end tie fields: balances, diff, per-check status
  - overall per-account status

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
