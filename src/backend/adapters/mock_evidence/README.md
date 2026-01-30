# Mock Evidence Adapters (JSON Fixtures)

These helpers normalize **JSON fixtures** into canonical evidence models used by the rules engine.
They perform **no I/O** and are intended for tests and early-stage development when real connectors
and file parsers are not available.

## Evidence manifest → EvidenceBundle

Use `evidence_bundle_from_manifest()` with a manifest shaped like:

```json
{
  "evidence": [
    {
      "evidence_type": "statement_balance_attachment",
      "amount": "4580.25",
      "statement_end_date": "2025-11-30",
      "uri": "fixture://paypal_activity_statement",
      "meta": { "account_ref": "name::Paypal AUD Account", "currency": "AUD" }
    },
    {
      "evidence_type": "petty_cash_support",
      "amount": "250.00",
      "as_of_date": "2025-11-30",
      "uri": "fixture://petty_cash_support_placeholder"
    }
  ]
}
```

### Required fields
- `evidence_type` (string)

### Optional fields
- `amount`, `as_of_date`, `statement_end_date`, `uri`, `meta`, `source`

## Reconciliation report → ReconciliationSnapshot

Use `reconciliation_snapshot_from_report()` with a JSON reconciliation report fixture.
The adapter expects:
- `account.name`
- `period.ending`
- `summary.statement_ending_balance`
- `summary.register_balance_as_of.{date,balance}` (optional)

Notes:
- If `account_ref` is not provided, the adapter uses `account.id` when present,
  else falls back to `name::<account_name>` (fixture-only convention).
- `statement_end_date` uses `period.ending` when present.
- `book_balance_as_of_period_end` is set **only** when the register balance date
  matches `period.ending` (strict).
