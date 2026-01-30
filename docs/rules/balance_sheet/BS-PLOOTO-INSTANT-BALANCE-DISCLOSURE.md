# BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE — Plooto Instant live balance identified

## Best Practice Reference
Plooto

## Why it matters
Plooto Instant is a top-up “wallet” balance funded from bank accounts and used to pay suppliers. It behaves like a cash-equivalent balance and should be accurately reflected in the books.

This rule is a **disclosure/FYI** check: surface any Plooto Instant balance so the reviewer can decide whether to
inform the client or transfer funds back based on client practice.

## Sources & required data
No Plooto API or evidence upload is required; this rule uses the Balance Sheet account in QBO.

Required:
- QBO Balance Sheet snapshot as-of `period_end`
Notes:
- Plooto Instant accounts only appear in QBO once Instant is used; multiple currencies may create multiple accounts.

## Config parameters
Config model: `PlootoInstantBalanceDisclosureRuleConfig`
- `enabled`
- `account_ref` (optional) — QBO Balance Sheet account representing Plooto Instant
- `account_name` (optional label)
- `account_name_match` (default `Plooto Instant`) — used for name inference when `account_ref` is not configured
- `allow_name_inference` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`) — use `NOT_APPLICABLE` if “can’t check” should be treated as N/A
- `amount_quantize` (optional)
- Severity mapping defaults: PASS INFO / WARN LOW / NEEDS_REVIEW MED / NOT_APPLICABLE INFO

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine the Plooto Instant account(s):
   - If `account_ref` configured → use it
   - Else if `allow_name_inference` → find accounts whose name includes `account_name_match`
3. If no matching account is found → status = `missing_data_policy`
4. Evaluate each matching account balance:
   - If balance is `0` → `PASS`
   - If balance is `> 0` or `< 0` → `WARN` with the amount
5. Overall status is `WARN` if any matching account is non-zero, otherwise `PASS`

## Outputs
- `details[]` includes per-account balance and whether it was inferred by name match
- `human_action` advises whether to disclose/transfer the balance when `WARN`
