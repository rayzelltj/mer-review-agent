# BS-TAX-FILINGS-UP-TO-DATE — Sales tax filings completed through most recent period

## Best Practice Reference
Tax accounts

## Why it matters
Sales tax returns should be filed through the most recent required period based on the agency’s cadence.

## Sources & required data
Required:
- QBO TaxAgency
- QBO TaxReturn

## Config parameters
Config model: `TaxFilingsUpToDateRuleConfig`
- `enabled`
- `tax_agencies_evidence_type` (default `tax_agencies`)
- `tax_returns_evidence_type` (default `tax_returns`)
- `exclude_agency_name_patterns` (default `["no tax agency"]`)
- `delinquent_status` (default `FAIL`)
- `missing_data_policy` (default `NEEDS_REVIEW`)

## Evidence item shape (required fields)
- `tax_agencies` → `meta.items[]` with `id`, `display_name`, `last_file_date`, `tax_tracked_on_sales`
- `tax_returns` → `meta.items[]` with `agency_id`, `start_date`, `end_date`, `file_date`

## Evaluation logic (step-by-step)
1. If disabled → `NOT_APPLICABLE`
2. If agency/return evidence missing → `missing_data_policy`
3. Filter to sales tax agencies (exclude “No Tax Agency”)
4. Infer cadence from the latest filed return period length (monthly/quarterly/annual)
5. Use the latest **period end** among filed returns (not file date)
6. Compute expected period end as the most recent scheduled period end `<= period_end`,
   rolling forward/backward from the latest covered end using the cadence (no calendar quarters)
7. If latest filed return end date < expected end → `delinquent_status`
7. Otherwise → `PASS`

## Outputs
- `details[]` includes per-agency cadence and expected period end
