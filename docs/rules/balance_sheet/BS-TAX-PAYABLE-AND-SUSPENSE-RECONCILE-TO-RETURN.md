# BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN — Tax payable/suspense reconcile to most recent return

## Best Practice Reference
Tax accounts

## Why it matters
Tax payable/suspense balances should reconcile to the expected return for the most recent completed filing period,
with payments/refunds offsetting the outstanding amount.

## Sources & required data
Required:
- Balance Sheet snapshot
- QBO TaxAgency
- QBO TaxReturn
- QBO TaxPayment

## Config parameters
Config model: `TaxPayableAndSuspenseReconcileRuleConfig`
- `enabled`
- `tax_agencies_evidence_type` (default `tax_agencies`)
- `tax_returns_evidence_type` (default `tax_returns`)
- `tax_payments_evidence_type` (default `tax_payments`)
- `account_name_patterns` (default includes GST/HST/PST payable + suspense variants)
- `refund_grace_days` (default 60)
- `delinquent_status` (default `FAIL`)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Evidence item shape (required fields)
- `tax_agencies` → `meta.items[]` with `id`, `display_name`
- `tax_returns` → `meta.items[]` with `agency_id`, `start_date`, `end_date`, `file_date`, `net_tax_amount_due`
- `tax_payments` → `meta.items[]` with `payment_date`, `payment_amount`, `refund`, optional `agency_id`

## Evaluation logic (step-by-step)
1. If disabled → `NOT_APPLICABLE`
2. If evidence missing → `missing_data_policy`
3. Identify tax accounts by name patterns (exclude report totals)
4. Map accounts to agencies (by agency name, GST/HST → CRA, PST → Finance)
   - Unmapped accounts are flagged but do not stop reconciliation of mapped accounts
5. Determine the expected filing period end using rolling cadence (no calendar quarters)
6. Select target return for that expected period (or latest <= expected)
7. Expected total = return due − payments (through `period_end`)
8. Compare combined payable+suspense balance to expected total (exact match)
9. Mismatch → `delinquent_status` (default FAIL)
10. Refunds: if core reconciliation passes and refund aged beyond grace window → WARN
11. Placement issues (negative payable or suspense placement) → WARN/NOTE only

## Outputs
- `details[]` includes per-agency balances, expected period end, return amounts, payment offsets, and notes
