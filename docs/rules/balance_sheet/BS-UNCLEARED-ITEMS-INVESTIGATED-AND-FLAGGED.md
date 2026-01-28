# BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED — Uncleared transactions are investigated and explained

## Best Practice Reference
Bank reconciliations → Uncleared items

## Why it matters
Uncleared (outstanding) items that remain on the reconciliation for a prolonged period can indicate:
- mispostings (wrong account, duplicate entry)
- missing bank transactions (bank error or feed issue)
- deposits/payments not processed as expected
- stale items that require client clarification

As a control, uncleared items **older than 2 months** should be flagged for investigation and explanation.

## Sources & required data
This rule is adapter-friendly and expects structured “uncleared items” from the reconciliation detailed report (PDF/CSV/spreadsheet parsing is out of scope for the rule).

Required:
- `ReconciliationSnapshot[]` including `statement_end_date` (the reconciliation “as at” date / period ending date)
- Uncleared items as-at the statement end date, provided in `ReconciliationSnapshot.meta`

Important:
- Reconciliation detailed reports often split uncleared items into **“as at”** and **“after date”** sections.
- This rule evaluates only **“as at”** items and explicitly **ignores** the “after date” section.

## Config parameters
Config model: `UnclearedItemsInvestigatedAndFlaggedRuleConfig`
- `enabled`
- `expected_accounts[]` (optional)
  - If set, missing any expected account reconciliation snapshot → `missing_data_policy`
  - If empty, evaluates all provided reconciliation snapshots
- `months_old_threshold` (default `2`)
  - Flags “as at” uncleared items where `txn_date < statement_end_date - months_old_threshold` (calendar months; strict “older than”)
- `stale_item_status` (default `WARN`)
  - Status to emit when stale items are found (`WARN` by default; can be configured to `FAIL`)
- `max_flagged_items_in_detail` (default `20`)
  - Caps the number of flagged items included in `details[]` for readability
- `missing_data_policy` (default NEEDS_REVIEW)
- Severity mapping (defaults): PASS INFO / WARN LOW / FAIL HIGH / NEEDS_REVIEW MED / NOT_APPLICABLE INFO

## Required `ReconciliationSnapshot.meta` shape (adapter responsibility)
Preferred canonical shape:
```json
{
  "uncleared_items": {
    "as_at": [
      { "txn_date": "YYYY-MM-DD", "description": "...", "amount": "123.45", "type": "Payment|Deposit", "reference": "..." }
    ],
    "after_date": [
      { "txn_date": "YYYY-MM-DD", "description": "...", "amount": "123.45" }
    ]
  }
}
```

Accepted for adapter convenience:
- `meta["uncleared_items_as_at"] = [...]`
- `meta["uncleared_items_after_date"] = [...]`

## Evaluation logic (step-by-step)
1. If `enabled == false` → `NOT_APPLICABLE`
2. Determine accounts in-scope:
   - If `expected_accounts[]` is set → use that list
   - Else → use all provided `ReconciliationSnapshot[]`
3. For each in-scope account:
   - If snapshot missing → `missing_data_policy`
   - If `statement_end_date` missing → `missing_data_policy`
   - Read uncleared items “as at” from `meta`
     - If missing → `missing_data_policy`
     - If any item date is missing/unparseable → `missing_data_policy` (to avoid silently under-flagging)
   - Compute `threshold_date = statement_end_date - months_old_threshold` (calendar months)
   - Flag items where `txn_date < threshold_date`
   - If any flagged → `stale_item_status` else PASS
4. Overall status is the worst across accounts

## Outputs
- `details[]` (one per evaluated account) includes:
  - `as_at_date`, `threshold_date`
  - counts for “as at”, ignored “after date”, invalid dates, and flagged items
  - a bounded sample of flagged items (date/description/amount)
- `human_action` prompts review and explicitly suggests checking with the client

