# BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE — Plooto Instant live balance identified

## Best Practice Reference
Plooto

## Why it matters
Plooto Instant is a top-up “wallet” balance funded from bank accounts and used to pay suppliers. It behaves like a cash-equivalent balance and should be accurately reflected in the books.

Per policy, the Plooto Instant balance **should be zero at period end**. If it is non-zero, it should be investigated, explained, and cleared.

## Sources & required data
No Plooto API is required for this rule; it uses a Balance Sheet account in QBO plus a period-end evidence amount for the Plooto Instant live balance.

Required:
- QBO Balance Sheet snapshot as-of `period_end` including the configured Plooto Instant account
- Plooto Instant “live balance” evidence amount as-of `period_end` (screenshot/export/manual extraction)

## Config parameters
Config model: `PlootoInstantBalanceDisclosureRuleConfig`
- `enabled`
- `account_ref` (required) — QBO Balance Sheet account representing Plooto Instant
- `account_name` (optional label)
- `evidence_type` (default `plooto_instant_live_balance`)
- `require_evidence_as_of_date_match_period_end` (default true)
  - If true, evidence must include an `as_of_date` equal to `period_end` (mismatches are flagged for review)
- `amount_quantize` (optional)
- Severity mapping defaults: PASS INFO / FAIL HIGH / NEEDS_REVIEW MED / NOT_APPLICABLE INFO

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If `account_ref` missing → `NEEDS_REVIEW`
3. If Balance Sheet account missing → `NEEDS_REVIEW`
4. If evidence amount missing/unavailable → `NEEDS_REVIEW`
5. If evidence `as_of_date` missing or not equal to `period_end` (when required) → `NEEDS_REVIEW`
6. Compare Plooto live balance to QBO Balance Sheet account:
   - If mismatch → `FAIL`
   - If match but non-zero → `FAIL` (Plooto Instant should be zero)
   - If match and zero → `PASS`

## Outputs
- `details[]` includes BS balance, Plooto live balance, difference, and evidence metadata
- `human_action` requests missing evidence or directs reconciliation/clearing actions for FAIL

