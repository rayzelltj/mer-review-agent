# BS-CLEARING-ACCOUNTS-ZERO — Sales clearing accounts should be within tolerance at period end

## Best Practice Reference
Clearing accounts (sales clearing tolerance)

## Why it matters
Sales clearing accounts (typically in Current Assets) should “wash out” at month end or remain within a tolerance tied
to platform sales; lingering balances can indicate posting errors, timing issues, or unreconciled activity.

## Sources & required data
- QBO Balance Sheet snapshot as-of `period_end`
  - For each configured account: `account_ref`, `name`, `balance`
- `period_end` date
- (Optional) P&L revenue total for `% of revenue` tolerances

## Config parameters
Config model: `ClearingAccountsZeroRuleConfig` (`common.rules_engine.config`)
- `enabled` (bool)
- `accounts[]` (list)
  - `account_ref` (required) — stable identifier from adapter/QBO
  - `account_name` (optional label)
  - `threshold` (optional override) — `floor_amount`, `pct_of_revenue`
- `default_threshold` — used when an account override has no `threshold`
- `missing_data_policy` — when a configured account is missing from the Balance Sheet snapshot
  - `NEEDS_REVIEW` (default) or `NOT_APPLICABLE`
- `current_asset_types` — account types treated as sales clearing
- If `accounts[]` is empty, accounts are inferred by `name` containing `"clearing"` (case-insensitive) **and**
  account type in `current_asset_types`
- `unconfigured_threshold_policy` — status to emit for **non-zero** balances when no thresholds are configured (TBD business policy)
  - Default: `NEEDS_REVIEW`
- `amount_quantize` (optional) — Decimal quantization for comparisons (e.g. `"0.01"` for cents)
- Severity (fixed mapping from status)
  - PASS → INFO
  - WARN → LOW
  - FAIL → HIGH
  - NEEDS_REVIEW → MEDIUM
  - NOT_APPLICABLE → INFO

### Threshold derivation (TBD)
`VarianceThreshold` is currently `max(floor_amount, abs(revenue_total) * pct_of_revenue)`.
When the account name matches an ecommerce platform, the default threshold is
`10%` of the corresponding platform sales (Income lines in P&L).
This is a placeholder mechanism; acceptable variance should be explicitly set per client/account (KYC/SOP).

Reasonable options to decide later:
1. Per-account absolute limits (preferred for clearing accounts)
2. % of revenue cap (secondary backstop)
3. Hybrid: absolute floor + % of revenue ceiling/floor (requires explicit policy)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine accounts to evaluate:
   - If `accounts[]` provided → use it (only current-asset clearing accounts are in scope)
   - Else → infer accounts by name match **and** current-asset account type
3. For each account:
   - If account missing from Balance Sheet snapshot → `missing_data_policy`
   - Quantize amounts if `amount_quantize` configured
   - If `abs(balance) == 0` → PASS (per-account)
   - If no thresholds configured for this account and `abs(balance) != 0` → `unconfigured_threshold_policy` (TBD)
   - Else compute `allowed_variance` and classify:
     - `0 < abs(balance) <= allowed_variance` → WARN
     - `abs(balance) > allowed_variance` → FAIL
4. Overall status is the “worst” across accounts: FAIL > NEEDS_REVIEW > WARN > PASS > NOT_APPLICABLE

## Outputs
- `status`: PASS / WARN / FAIL / NEEDS_REVIEW / NOT_APPLICABLE
- `severity`: mapped from status (see defaults above)
- `summary`: includes a representative account, amount, allowed variance, and `period_end` for WARN/FAIL
- `details[]` (one per evaluated account) includes:
  - `account_ref` (as `RuleResultDetail.key`)
  - `account_name`
  - `period_end`
  - `balance`, `abs_balance`
  - `allowed_variance`
  - `threshold_floor_amount`, `threshold_pct_of_revenue`
  - `threshold_configured` (bool)
  - `inferred_by_name_match` (bool)
  - `threshold_source` (configured/platform_revenue/unconfigured)
  - `platform_revenue` (if inferred)
  - `platform_tokens` (tokens used to match P&L income lines)
  - per-account `status`

## Edge cases
- Negative balances: evaluated using `abs(balance)`
- Revenue missing: `pct_of_revenue` component treated as 0
- Amount rounding: only applied when `amount_quantize` is set (otherwise exact Decimal comparisons)
- Accounts missing type/subtype data are flagged as NEEDS_REVIEW (cannot classify sales vs non-sales).
- Non-sales clearing accounts are handled by `BS-CLEARING-ACCOUNTS-NON-SALES-ZERO`.

## Test matrix
| Scenario | Setup | Expected |
|---|---|---|
| Exactly zero | balance = 0 | PASS / INFO |
| Non-zero within variance | balance <= allowed | WARN / LOW |
| Non-zero outside variance | balance > allowed | FAIL / HIGH |
| Missing configured account | account_ref not in snapshot | NEEDS_REVIEW (or NOT_APPLICABLE if configured) |
| No accounts found | no sales clearing accounts | NOT_APPLICABLE |
| Rounding boundary | `amount_quantize="0.01"`, balance `0.004` | PASS |
