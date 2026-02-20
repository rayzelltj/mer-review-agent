# BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END — Bank/Credit Card reconciliation through period end

## Intent
Evaluate all **active** bank and credit-card accounts (from Chart of Accounts) using a deterministic reconciliation equation:

1. statement ending balance (attachment evidence),
2. trial-balance register balance at month end,
3. unreconciled transaction sums from Transaction List by Account.

## Inputs (required)
- `RuleContext.period_end`
- `EvidenceBundle`:
  - CoA bank/cc scope evidence (`chart_of_accounts_evidence_type`)
  - trial-balance register balances (`trial_balance_evidence_type`)
  - transaction-list unreconciled sums (`transaction_list_evidence_type`)
  - statement ending balance evidence (`statement_balance_attachment_evidence_type`)

## Scope rules
- Primary scope source: Chart of Accounts (`AccountType in {"Bank","Credit Card"}` and active account filter).
- `expected_accounts[]` can explicitly set scope.
- `include_accounts[]` and `exclude_accounts[]` apply as overrides.
- Fallback name heuristics are only used when CoA scope evidence is missing.

## Equation
- `expected_outstanding = register_balance - statement_ending_balance`
- `S1 = sum(not reconciled as of period_end: blank + "C")`
- `S2 = sum(not reconciled between period_end and statement/reconciliation date)`

Decision:
- PASS if `expected_outstanding == S1`
- PASS if `(expected_outstanding - S1) == S2`
- WARN otherwise (data present but mismatch)
- NEEDS_REVIEW for missing required data

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, or no in-scope accounts
- NEEDS_REVIEW:
  - missing CoA scope evidence (and no fallback scope),
  - missing statement balance,
  - missing trial-balance register balance,
  - missing transaction-list S1/S2 data or missing clear-status column
- PASS:
  - all in-scope accounts satisfy equation checks
- WARN:
  - at least one in-scope account has an equation mismatch

## Output expectations
Per-account `details[]` includes:
- account scope details (`account_type`, `account_active`, scope source)
- statement/register balances
- `expected_outstanding`, `S1`, `S2`
- explicit equation checks and pass flags
- parser diagnostics (`clear_status_column_found`, parsed/ignored row counts)

## Evidence notes
- Statement PDF formats vary; if amount is not directly extracted/provided, result is `NEEDS_REVIEW`.
- Transaction-list parser uses status-based unreconciled classification and date windows.

## Tests
- `src/backend/tests/rules_engine/test_bs_bank_reconciled_through_period_end.py`
- `src/backend/tests/rules_engine/test_blackbird_fabrics_samples_bank_reconciled.py`
