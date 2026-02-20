# BS-AP-AR-PAID-AFTER-MONTH-END-NOTED — Items paid after month-end are annotated

## Intent
When a period-end AP/AR open item is no longer present in a later aging-detail snapshot, treat it as settled after month-end and surface a reviewer note for MER commentary.

## Inputs (required)
- AP aging detail rows (`ap_aging_detail_rows`) as of period end.
- AR aging detail rows (`ar_aging_detail_rows`) as of period end.
- Follow-up AP/AR aging detail rows after period end (or at explicit `comparison_as_of_date`).

## Config (knobs)
- `ap_detail_rows_evidence_type`, `ar_detail_rows_evidence_type`
- `require_period_end_evidence_date_match` (default `true`)
- `comparison_as_of_date` (optional explicit review date)
- `settled_item_status` (default `NEEDS_REVIEW`)
- `max_noted_items_in_detail` (default `25`)

## Decision table
- PASS: comparison succeeded and no period-end items disappeared by follow-up date.
- WARN/FAIL/NEEDS_REVIEW: period-end items disappeared (status uses `settled_item_status`).
- NEEDS_REVIEW/NOT_APPLICABLE: missing or incomplete evidence (driven by `missing_data_policy`).
- NOT_APPLICABLE: no AP/AR period-end detail evidence exists.

## Output expectations
- Detail keys:
  - `ap_paid_after_month_end`
  - `ar_paid_after_month_end`
- Each detail includes period-end and follow-up as-of dates, settled counts, and settled item notes.
- Notes explicitly instruct adding payment/receipt date + method to MER comments.

## Tests
- `tests/rules_engine/test_bs_ap_ar_paid_after_month_end_noted.py`
