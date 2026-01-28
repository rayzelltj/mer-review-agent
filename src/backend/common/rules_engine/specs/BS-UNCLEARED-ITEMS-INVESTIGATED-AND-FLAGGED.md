# BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED — Uncleared transactions are investigated and explained

## Intent
Identify uncleared items on bank reconciliations that are sufficiently old that they require investigation and explanation.

This rule focuses on **uncleared items as at the reconciliation statement end date** (i.e., the report’s “as at” section) and explicitly **ignores** uncleared items listed “after date”.

## Inputs (required)
- `RuleContext.reconciliations[]` (`ReconciliationSnapshot`) containing, per account:
  - `statement_end_date` (treated as the reconciliation “as at” date / period ending date)
  - `meta` containing structured uncleared items from the detailed reconciliation report

## Inputs (optional)
- `BalanceSheetSnapshot` at `RuleContext.period_end` for friendly account name fallbacks

## Config (knobs)
Config model: `UnclearedItemsInvestigatedAndFlaggedRuleConfig`
- `enabled`
- `expected_accounts[]` (optional)
  - if configured: missing any expected account snapshot triggers `missing_data_policy`
  - if empty: evaluates all provided reconciliation snapshots
- `months_old_threshold` (default `2`)
  - “More than 2 months old” is evaluated as: `txn_date < statement_end_date - 2 calendar months` (strictly earlier)
- `stale_item_status` (default `WARN`; can be set to `FAIL` per client policy)
- `max_flagged_items_in_detail` (default `20`)
- `missing_data_policy`

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

Date parsing expectations:
- Prefer ISO (`YYYY-MM-DD`) from adapters.
- `DD/MM/YYYY` is also accepted (to match common reconciliation report formatting).

## Decision table
- NOT_APPLICABLE: `enabled == false`
- NEEDS_REVIEW:
  - no reconciliation snapshots provided, **or**
  - expected account snapshot missing (when `expected_accounts` configured), **or**
  - `statement_end_date` missing, **or**
  - “as at” uncleared list missing, **or**
  - any “as at” uncleared item is missing/has an unparseable transaction date
- PASS: no “as at” uncleared item has `txn_date < statement_end_date - months_old_threshold`
- WARN/FAIL: one or more “as at” uncleared items are older than the threshold (status is `stale_item_status`)

## Edge cases
- “After date” items are ignored even if old (the rule evaluates the reconciliation **as at** the statement end date).
- Threshold is calendar-month based (not “60 days”) to align with typical accounting review policies.

## Output expectations
- One `details[]` entry per evaluated reconciliation snapshot, including:
  - `as_at_date`, `threshold_date`, counts, and a bounded sample of flagged items
- `human_action` set for WARN/FAIL/NEEDS_REVIEW, prompting review and client follow-up.

## Tests
- `src/backend/tests/rules_engine/test_bs_uncleared_items_investigated_and_flagged.py`

