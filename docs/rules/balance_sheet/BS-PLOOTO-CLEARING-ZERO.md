# BS-PLOOTO-CLEARING-ZERO — Plooto Clearing should be zero at period end

## Best Practice Reference
Plooto

## Why it matters
Plooto Clearing is a control account used to settle Plooto activity. Per policy it should be **exactly zero** at
period end. Any non-zero balance indicates posting or timing issues that must be investigated and cleared.

## Sources & required data
Required:
- QBO Balance Sheet snapshot as-of `period_end`

## Config parameters
Config model: `PlootoClearingZeroRuleConfig`
- `enabled`
- `account_ref` (optional) — QBO Balance Sheet account representing Plooto Clearing
- `account_name` (optional label)
- `account_name_match` (default `Plooto Clearing`) — used for name inference when `account_ref` is not configured
- `allow_name_inference` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`)
- `amount_quantize` (optional)

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine the Plooto Clearing account:
   - If `account_ref` configured → use it
   - Else if `allow_name_inference` → find accounts whose name includes `account_name_match`
3. If no matching account is found → `NOT_APPLICABLE`
4. If the account balance is:
   - `0` → `PASS`
   - non-zero → `FAIL`

## Outputs
- `details[]` includes per-account balance and whether it was inferred by name match
- `human_action` directs clearing any non-zero balance when `FAIL`
