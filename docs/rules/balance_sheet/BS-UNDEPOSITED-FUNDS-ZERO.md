# BS-UNDEPOSITED-FUNDS-ZERO — Undeposited Funds should be zero at period end

## Best Practice Reference
Bank reconciliations

## Why it matters
Undeposited Funds should typically be cleared to actual bank deposits by month end; a lingering balance can indicate deposit timing issues or missing deposit postings.

## Sources & required data
- QBO Balance Sheet snapshot as-of `period_end` for Undeposited Funds account(s)
- `period_end` date
- (Optional) P&L revenue total for `% of revenue` tolerances

## Config parameters
Config model: `ZeroBalanceRuleConfig`
- `enabled`
- `accounts[]` (optional; if empty, accounts are inferred by name containing `undeposited`)
  - `account_ref` (required)
  - `account_name` (optional label)
  - `threshold` (optional override) — `floor_amount`, `pct_of_revenue`
- `default_threshold`
- `missing_data_policy` — when a configured account is missing from the Balance Sheet snapshot
- `unconfigured_threshold_policy` — status to emit for **non-zero** balances when no thresholds are configured (TBD business policy)
  - Default: `NEEDS_REVIEW`
- `amount_quantize` (optional)
- Severity (fixed mapping from status): same as `BS-CLEARING-ACCOUNTS-ZERO`

### Threshold derivation (TBD)
Acceptable variance policy is not defined yet. Current placeholder supports:
1. Per-client/per-account absolute threshold
2. % of revenue threshold
3. Hybrid (`max(floor_amount, abs(revenue_total) * pct_of_revenue)`)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If `accounts[]` empty → infer accounts by name containing `undeposited`
3. If no accounts found → `NEEDS_REVIEW`
4. For each account:
   - If missing in Balance Sheet snapshot → `missing_data_policy`
   - Quantize if configured
   - If `abs(balance) == 0` → PASS (per-account)
   - If no thresholds configured for this account and non-zero → `unconfigured_threshold_policy` (TBD)
   - Else classify using `allowed_variance`:
     - within variance → WARN
     - outside variance → FAIL
4. Overall status is the worst across accounts

## Outputs
- `details[]` includes account ref/name, period end, balance, threshold, allowed variance, per-account status, and whether it was inferred by name
- `summary` includes a representative account, amount, allowed variance, and `period_end` for WARN/FAIL

## Edge cases
- Negative balances evaluated by absolute value
- Missing revenue yields floor-only tolerance

## Test matrix
| Scenario | Expected |
|---|---|
| Exactly zero | PASS / INFO |
| Non-zero within variance | WARN / LOW |
| Non-zero outside variance | FAIL / HIGH |
| No accounts found (configured or inferred) | NEEDS_REVIEW |
| Account missing from snapshot | NEEDS_REVIEW (or NOT_APPLICABLE if configured) |
| Threshold unconfigured and non-zero | `unconfigured_threshold_policy` (default NEEDS_REVIEW) |
