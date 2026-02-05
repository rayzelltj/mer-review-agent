# BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN — Tax payable/suspense reconcile to most recent return

## Intent
Verify tax payable/suspense balances reconcile to the expected return (most recent completed period) and tax payments/refunds.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot`
- Evidence: `tax_agencies`, `tax_returns`, `tax_payments`

## Config (knobs)
Config model: `TaxPayableAndSuspenseReconcileRuleConfig`
- `enabled`
- `tax_agencies_evidence_type`
- `tax_returns_evidence_type`
- `tax_payments_evidence_type`
- `account_name_patterns` (includes GST/HST/PST payable + suspense variants)
- `refund_grace_days`
- `missing_data_policy`
- `delinquent_status`

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, or no tax accounts in scope
- `missing_data_policy`:
  - evidence missing, agency mapping missing (for those accounts), or return missing for expected period
- PASS:
  - Combined payable+suspense balance equals expected return balance
- WARN:
  - Refund case is aged beyond grace window (balances match), or negative payable placement issue
- `delinquent_status` (default FAIL):
  - Combined balance does not match expected return balance
- NEEDS_REVIEW:
  - Missing data or unmapped accounts

## Output expectations
- `details[]` includes per-agency return balance, payment offsets, and balance sheet balance.

## Tests
- `src/backend/tests/rules_engine/test_bs_tax_payable_and_suspense_reconcile_to_return.py`
