# QBO Adapters

These modules normalize **raw QBO payloads** (typically JSON returned by the QBO API) into the canonical
domain models consumed by the rules engine (`common.rules_engine.*`).

## What belongs here
- Parsing QBO Report Service payloads into snapshots (Balance Sheet, P&L, etc.)
- Joining QBO payloads to enrich canonical fields (e.g., account `type`/`subtype` from Chart of Accounts)
- Returning deterministic models that can be unit-tested from saved fixtures

## What must NOT belong here
- OAuth flows, HTTP requests, pagination, retries (connector responsibility)
- Any rule evaluation logic (rules engine responsibility)

## Balance Sheet

`adapters.qbo.balance_sheet.balance_sheet_snapshot_from_report()` converts a QBO `reports/BalanceSheet`
response into a `BalanceSheetSnapshot`:

- `Header.EndPeriod` → `BalanceSheetSnapshot.as_of_date`
- Extracts only `Rows.Row[].type == "Data"` rows with a stable account `id` by default
- Can enrich `AccountBalance.type/subtype` using `account_type_map_from_accounts_payload()` output.
 - If `include_summary_totals=True`, also captures Summary rows whose label contains "Total" as
   `report::Total ...` accounts.

This enrichment matters because bank/credit-card scope inference relies on `type/subtype`.

## Accounts (Chart of Accounts)

`adapters.qbo.accounts.account_type_map_from_accounts_payload()` builds a mapping from
QBO Account `Id` → `{AccountType, AccountSubType}`.

Supported shapes:
- `{"QueryResponse": {"Account": [ ... ]}}` (recommended)
- `{"Account": [ ... ]}`
- `{"Account": { ... }}`

## Profit & Loss

`adapters.qbo.profit_and_loss.profit_and_loss_snapshot_from_report()` converts a QBO
`reports/ProfitAndLoss` response into a `ProfitAndLossSnapshot`:

- `Header.StartPeriod` → `period_start`
- `Header.EndPeriod` → `period_end`
- Extracts **Total Income** as `totals["revenue"]` using:
  - Primary: `group == "Income"` summary value
  - Fallback: summary label `Total Income`
- If `summarize_by_month=True`, selects the **MER month column** based on `Header.EndPeriod`
  (errors if the month column is missing).

This total feeds variance-based rules (e.g., Undeposited Funds / Clearing thresholds).

## Pipeline helper

`adapters.qbo.pipeline.build_qbo_snapshots()` is a convenience function that accepts:
- Balance Sheet report JSON
- Profit & Loss report JSON (optional)
- Accounts QueryResponse JSON (optional)

It returns `QBOAdapterOutputs` containing the canonical snapshots and the account type map.

`adapters.qbo.pipeline.build_qbo_aging_evidence()` accepts AP/AR aging report payloads and returns an
`EvidenceBundle` with the evidence types produced by `aging_report_to_evidence()`.

## Aging reports (AP/AR)

`adapters.qbo.aging_reports.aging_report_to_evidence()` converts QBO aging reports into `EvidenceItem`s.
For each report, it emits:
- `<ap|ar>_aging_<summary|detail>_total`
- `<ap|ar>_aging_<summary|detail>_over_60` (with item-level `meta.items[]`)
- `<ap|ar>_aging_detail_rows` (detail rows with `open_balance` in `meta.items[]`)

Example:

```python
from adapters.qbo.aging_reports import aging_report_to_evidence

evidence_items = []
evidence_items += aging_report_to_evidence(ap_summary_report, report_type="ap", report_kind="summary")
evidence_items += aging_report_to_evidence(ap_detail_report, report_type="ap", report_kind="detail")
evidence_items += aging_report_to_evidence(ar_summary_report, report_type="ar", report_kind="summary")
evidence_items += aging_report_to_evidence(ar_detail_report, report_type="ar", report_kind="detail")
```

These evidence types are used by:
- `BS-AP-SUBLEDGER-RECONCILES` / `BS-AR-SUBLEDGER-RECONCILES` (total evidence)
- `BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS` (over-60 evidence)
