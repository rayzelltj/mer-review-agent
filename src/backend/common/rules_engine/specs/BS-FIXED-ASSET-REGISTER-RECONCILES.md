# BS-FIXED-ASSET-REGISTER-RECONCILES — Fixed asset register reconciles to Balance Sheet

## Intent
Ensure month-end closing balances by fixed-asset class in the depreciation schedule and/or fixed asset register reconcile to QBO Balance Sheet balances.

## Inputs (required)
- `BalanceSheetSnapshot` as of period end.
- Fixed asset evidence (`fixed_asset_register_balance`) containing:
  - one row per asset class (`meta.items[]` with `asset_class` + `balance`), or
  - one evidence item per class (`amount` + `meta.asset_class`/`meta.account_name_match`).

## Config (knobs)
- `evidence_type` (default `fixed_asset_register_balance`)
- `require_evidence_as_of_date_match_period_end` (default true)
- `prefer_total_balance_sheet_lines` (default true)
- `missing_data_policy` (`NEEDS_REVIEW` or `NOT_APPLICABLE`)

## Decision table
- PASS: all asset classes match corresponding Balance Sheet balances.
- FAIL: one or more mapped asset classes have non-zero differences.
- NEEDS_REVIEW/NOT_APPLICABLE: missing evidence, unusable rows, or missing/ambiguous account mapping (per `missing_data_policy`).
- NOT_APPLICABLE: no fixed asset accounts in Balance Sheet snapshot.

## Output expectations
- One detail per evaluated asset class with:
  - register closing balance
  - matched BS account/balance
  - difference
  - status
- Includes mapping diagnostics (`match_error`, `candidate_accounts`) when not matched.

## Tests
- `tests/rules_engine/test_bs_fixed_asset_register_reconciles.py`
