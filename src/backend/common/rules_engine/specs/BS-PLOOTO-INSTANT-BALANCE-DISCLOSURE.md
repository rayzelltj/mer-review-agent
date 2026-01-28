# BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE — Plooto Instant live balance identified

## Intent
Ensure the Plooto Instant live balance is identified as of period end and matches the Balance Sheet amount recorded in QBO.

Per business policy, Plooto Instant **should be zero** at period end; any non-zero balance must be investigated and cleared.

This rule is **adapter-friendly**: it evaluates structured Balance Sheet snapshots and evidence items (no Plooto API required).

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `EvidenceBundle` containing a Plooto Instant “live balance” evidence item as of `period_end`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match is still expected after quantization)

## Config (knobs)
Config model: `PlootoInstantBalanceDisclosureRuleConfig`
- `enabled`
- `account_ref` (required) — the QBO Balance Sheet account representing Plooto Instant balance
- `account_name` (optional label)
- `evidence_type` (default `plooto_instant_live_balance`)
- `require_evidence_as_of_date_match_period_end` (default true)
  - when true, missing or mismatched evidence `as_of_date` triggers NEEDS_REVIEW
- `missing_data_policy` (not used directly; this rule uses NEEDS_REVIEW for unavailable values)

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - `account_ref` not configured, **or**
  - account not found in Balance Sheet snapshot, **or**
  - evidence item missing or evidence `amount` missing, **or**
  - `require_evidence_as_of_date_match_period_end == true` AND (evidence `as_of_date` missing OR `as_of_date != period_end`)
- FAIL:
  - `abs(bs_balance - plooto_live_balance) != 0` (exact match required), **or**
  - `bs_balance == plooto_live_balance != 0` (Plooto Instant must be zero)
- PASS:
  - `bs_balance == plooto_live_balance == 0`

## Edge cases
- Evidence and BS balances must be currency-consistent (adapter responsibility).
- If `amount_quantize` is set (e.g., cents), both values are quantized before comparison.

## Output expectations
- One `details[]` entry with:
  - `bs_balance`, `plooto_live_balance`, `difference`
  - evidence metadata (`evidence_type`, `evidence_as_of_date`)
- `human_action` set for FAIL/NEEDS_REVIEW to request evidence and/or reconcile the balance.

## Tests
- `src/backend/tests/rules_engine/test_bs_plooto_instant_balance_disclosure.py`

