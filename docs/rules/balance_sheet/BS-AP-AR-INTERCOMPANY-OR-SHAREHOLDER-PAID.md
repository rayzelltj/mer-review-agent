# BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID — Intercompany/shareholder-paid balances identified

## Best Practice Reference
Accounts Payable/Receivable

## Why it matters
Intercompany balances must agree across entities to ensure AP/AR is cleared appropriately and
intercompany balances remain consistent.

## Sources & required data
Required:
- QBO Balance Sheet snapshot as-of `period_end`
- Counterparty Balance Sheet evidence (from other entities) as-of `period_end`

## Config parameters
Config model: `ApArIntercompanyOrShareholderPaidRuleConfig`
- `enabled`
- `name_patterns` (default: `due to`, `due from`, `intercompany`, `inter-company`)
- `non_zero_only` (default true)
- `evidence_type` (default `intercompany_balance_sheet`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Evidence item shape (required fields)
Evidence item `intercompany_balance_sheet` must include:
- `as_of_date`
- `meta.items[]` with:
  - `counterparty` (company name)
  - `balance` (Balance Sheet balance from the counterparty)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Identify Balance Sheet accounts whose names match any `name_patterns`
3. If no matching accounts → `NOT_APPLICABLE`
4. If evidence missing or evidence date mismatch → `missing_data_policy`
5. For each matched account:
   - Extract counterparty name from account name
   - Compare absolute balances to counterparty Balance Sheet balance
6. If any missing/mismatched counterparty balance → `NEEDS_REVIEW`, else `PASS`

## Outputs
- `details[]` includes per-account comparisons and mismatch summary
- `human_action` requests reconciliation if mismatches exist
