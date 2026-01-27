# Rule Specs

These files are the human-readable “rulebook” for the rules engine.

- One file per rule: `<RULE_ID>.md`
- Keep them **implementation-accurate**. If rule logic changes, update the spec and the unit tests together.
- Specs describe *behavior* (inputs → outputs) and decision criteria; they intentionally avoid code-level details.

## Spec Template (copy/paste)

```md
# <RULE_ID> — <Rule Title>

## Intent
<1–3 sentences. Why this rule exists and what “good” looks like.>

## Inputs (required)
- <Snapshots/evidence required to evaluate PASS/WARN/FAIL.>

## Inputs (optional)
- <Optional inputs that refine thresholds or improve signal.>

## Config (knobs)
- <What can be configured per client (and per account if relevant).>

## Decision table
- PASS: <condition>
- WARN: <condition> (include reviewer note)
- FAIL: <condition>
- NEEDS_REVIEW: <missing data condition>
- NOT_APPLICABLE: <disabled condition / NA policy>

## Edge cases
- <e.g. revenue missing → floor-only tolerance>

## Output expectations
- `RuleResult.status`: …
- `RuleResult.details`: include … (per-account fields)
- `RuleResult.human_action`: set when …

## Tests
- <Test file path(s)>
- Covered cases: PASS / WARN / FAIL / NEEDS_REVIEW / NOT_APPLICABLE
```

