# BS-AP-SUBLEDGER-RECONCILES — Aged Payables Detail reconciles to Balance Sheet

## Intent
Ensure AP aging summary and detail totals reconcile to the Balance Sheet AP total as of period end.

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end` (include “Total Accounts Payable” line when possible)
- `EvidenceBundle` containing:
  - AP aging summary total
  - AP aging detail total
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match is expected after quantization)

## Config (knobs)
Config model: `ApSubledgerReconcilesRuleConfig`
- `enabled`
- `account_refs` (optional list)
- `account_name_match` (default `accounts payable`)
- `allow_name_inference` (default true)
- `summary_evidence_type` (default `ap_aging_summary_total`)
- `detail_evidence_type` (default `ap_aging_detail_total`)
- `require_evidence_as_of_date_match_period_end` (default true)

## Decision table
- NOT_APPLICABLE:
  - `enabled == false`, **or**
  - no matching accounts found
- NEEDS_REVIEW:
  - any configured `account_refs` are missing, **or**
  - summary/detail evidence missing or amount missing, **or**
  - summary/detail `as_of_date` missing or not equal to `period_end`
- FAIL:
  - `bs_total != summary_total`, **or**
  - `bs_total != detail_total`
- PASS:
  - `bs_total == summary_total == detail_total`

## Edge cases
- If a “Total Accounts Payable” line exists, the rule uses it instead of summing accounts.
- If multiple AP accounts match by name, the rule sums them.
- If `amount_quantize` is set (e.g., cents), all values are quantized before comparison.

## Output expectations
- `details[]` entries per matched account plus a totals comparison row
- `human_action` set for FAIL/NEEDS_REVIEW to request reconciliation

## Tests
- `src/backend/tests/rules_engine/test_bs_ap_subledger_reconciles.py`
