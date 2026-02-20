# BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END — Bank/Credit Card reconciliation through period end

## Best Practice Reference
Bank reconciliations -> Banks and credit cards

## Why it matters
Bank and credit-card balances should be supportable by statement balances, month-end register balances, and known unreconciled transactions.

## Scope
- Use Chart of Accounts as source of truth for in-scope accounts:
  - `AccountType == Bank` or `AccountType == Credit Card`
  - active accounts only (unless config says otherwise)

## Required evidence/data
- CoA bank/credit-card scope evidence
- Trial Balance register balances at period end
- Transaction List by Account data to compute:
  - `S1` unreconciled as of period end
  - `S2` unreconciled between period end and reconciliation/statement date
- Statement ending balance evidence (bank statement/activity statement)

## Equation checks
- `expected_outstanding = register_balance - statement_ending_balance`
- PASS if `expected_outstanding == S1`
- PASS if `(expected_outstanding - S1) == S2`
- WARN if equation mismatches with complete data
- NEEDS_REVIEW if required data is missing

## Notes
- Statement PDF formats vary. If extraction is unavailable and amount is not provided in evidence metadata, result is `NEEDS_REVIEW`.
