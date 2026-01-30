# BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE — Plooto Instant live balance identified

## Intent
Surface any Plooto Instant balance at period end so reviewers can decide whether to notify the client or transfer funds
back based on client practice.

This rule is **adapter-friendly**: it evaluates Balance Sheet snapshots only (no Plooto API or evidence required).

## Inputs (required)
- `RuleContext.period_end`
- `BalanceSheetSnapshot` at `period_end`
- `ClientRulesConfig` for this rule

## Inputs (optional)
- `amount_quantize` for rounding (exact match is still expected after quantization)

## Config (knobs)
Config model: `PlootoInstantBalanceDisclosureRuleConfig`
- `enabled`
- `account_ref` (optional) — the QBO Balance Sheet account representing Plooto Instant balance
- `account_name` (optional label)
- `account_name_match` (default `Plooto Instant`) — used for name inference when `account_ref` is not configured
- `allow_name_inference` (default true)
- `missing_data_policy` (default `NEEDS_REVIEW`) — status to use when no matching account is found

## Decision table
- NOT_APPLICABLE: `enabled == false`
- `missing_data_policy`:
  - no `account_ref` configured **and** no account matches `account_name_match`
  - `account_ref` configured but account not found in Balance Sheet snapshot
- WARN:
  - any matching account balance is non-zero
- PASS:
  - all matching account balances are zero

## Edge cases
- If multiple Plooto Instant accounts exist (e.g., multiple currencies), each is evaluated independently.
- Plooto Instant accounts may not exist in QBO until Instant is used; handle missing accounts via `missing_data_policy`.
- If `amount_quantize` is set (e.g., cents), balances are quantized before comparison.

## Output expectations
- One `details[]` entry per matching account with:
  - `balance`, `inferred_by_name_match`
- `human_action` set for WARN to prompt disclosure/transfer decision.

## Tests
- `src/backend/tests/rules_engine/test_bs_plooto_instant_balance_disclosure.py`
