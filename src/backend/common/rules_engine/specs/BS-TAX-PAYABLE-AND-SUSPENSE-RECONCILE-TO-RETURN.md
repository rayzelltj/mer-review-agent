# BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN — Tax payable/suspense reconcile to most recent return

## Intent
Verify tax payable/suspense balances reconcile to the most recent filed return, with strict placement policy:
- Tax payable must be zero.
- Tax suspense must tie to the most recent filed return amount, adjusted by mapped payments/refunds for that filing period.

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
- `missing_data_policy`
- `delinquent_status`

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, or no tax accounts in scope
- `missing_data_policy`:
  - evidence missing, agency mapping missing (for those accounts), or return missing for expected period
- PASS:
  - `payable == 0` and `suspense == expected_suspense`
- FAIL:
  - payable is non-zero
- WARN:
  - optional via `delinquent_status` when suspense does not match expected value
- `delinquent_status` (default FAIL):
  - suspense does not match expected value
- NEEDS_REVIEW:
  - Missing data or unmapped accounts

## Output expectations
- `details[]` includes per-agency return balance, payment offsets, and balance sheet balance.

## Tests
- `src/backend/tests/rules_engine/test_bs_tax_payable_and_suspense_reconcile_to_return.py`
