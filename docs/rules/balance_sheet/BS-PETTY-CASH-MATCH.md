# BS-PETTY-CASH-MATCH — Petty cash matches between Balance Sheet and client supporting doc

## Best Practice Reference
Petty cash

## Why it matters
Petty cash is high-risk for misstatement; tying the book balance to client support helps detect missing receipts, miscategorizations, or stale balances.

## Sources & required data
- QBO Balance Sheet snapshot as-of `period_end` for the configured petty cash account
- Client supporting document amount as-of `period_end` (evidence)
  - `EvidenceItem.evidence_type` defaults to `petty_cash_support`
- `period_end` date

## Config parameters
Config model: `PettyCashMatchRuleConfig`
- `enabled`
- `account_ref` (required)
- `account_name` (optional label)
- `evidence_type` (default `petty_cash_support`)
- `missing_data_policy` — unused for this rule (account missing is treated as NOT_APPLICABLE)
- `amount_quantize` (optional)
- Severity mapping (defaults)
  - PASS → INFO, FAIL → HIGH, NEEDS_REVIEW → MEDIUM, NOT_APPLICABLE → INFO

### Supporting document availability policy (defined)
If the supporting document is non-existent/unavailable for the period → `NEEDS_REVIEW` (follow up with client).

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. If `account_ref` not configured → `NEEDS_REVIEW`
3. If petty cash account missing from Balance Sheet snapshot → `NOT_APPLICABLE`
4. If supporting evidence item or its amount is missing → `NEEDS_REVIEW`
5. Quantize if configured
6. Compute `difference = abs(bs_balance - support_amount)`
   - difference == 0 → PASS
   - difference > 0 → FAIL

## Outputs
- `details[]` includes:
  - account ref/name, `period_end`
  - `bs_balance`, `support_amount`, `difference`, and per-check status
- `evidence_used[]` includes the evidence item when present

## Edge cases
- Missing evidence never yields FAIL; it yields NEEDS_REVIEW per policy

## Test matrix
| Scenario | Expected |
|---|---|
| Support exists and matches | PASS / INFO |
| Support missing/unavailable | NEEDS_REVIEW / MEDIUM |
| Any difference | FAIL / HIGH |
| QBO account missing | NOT_APPLICABLE / INFO |
