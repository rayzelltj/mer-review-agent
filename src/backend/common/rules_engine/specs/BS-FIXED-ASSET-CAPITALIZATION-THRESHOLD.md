# BS-FIXED-ASSET-CAPITALIZATION-THRESHOLD — Capitalization threshold enforced

Ensure fixed-asset additions follow the client capitalization policy and surface abnormal month-over-month expense-line movement.

## Inputs

- Balance Sheet snapshot (current month + prior month)
- KYC evidence containing capitalization threshold
- Fixed asset account ledger transactions for the current month
- Profit and Loss month-over-month expense lines (current vs prior month)

## Core checks

1. Fixed asset threshold check:
- Compare fixed asset balances this month vs prior month.
- If there is an increase, evaluate fixed-asset ledger additions against the KYC capitalization threshold.
- Flag additions below threshold.

2. Expense anomaly check:
- Compare prior month and current month expense lines.
- Flag absolute % changes above configured threshold (default 10%).
- Ignore payroll/COGS patterns.

## Status behavior

- `FAIL`: any below-threshold fixed-asset addition (per `capitalization_violation_status`)
- `WARN`: abnormal expense-line changes detected (per `abnormal_expense_change_status`)
- `NEEDS_REVIEW`: missing prior-month/KYC/ledger/P&L evidence prevents full evaluation
- `PASS`: no below-threshold additions and no abnormal expense changes
- `NOT_APPLICABLE`: no fixed asset accounts in the balance sheet snapshot

## Config highlights

- `kyc_evidence_type` (default `kyc_profile`)
- `fixed_asset_ledger_evidence_type` (default `qbo_fixed_asset_ledger_transactions`)
- `pnl_expense_monthly_evidence_type` (default `qbo_pnl_expense_monthly`)
- `abnormal_change_pct` (default `0.10`)

