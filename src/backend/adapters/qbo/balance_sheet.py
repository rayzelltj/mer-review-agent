from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from common.rules_engine.models import BalanceSheetSnapshot
from .accounts import QBOAccountTypeInfo, account_type_map_from_accounts_payload


class QBOBalanceSheetAdapterError(ValueError):
    pass


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except Exception:
            return None
    return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        # Avoid float binary artifacts: go through str.
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # QBO reports are usually not localized, but commas do show up in some exports.
        s = s.replace(",", "")
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def _iter_rows(row_container: Any) -> Iterable[dict[str, Any]]:
    """
    Yield every dict row under the QBO report Rows tree.
    QBO structure is nested like Rows -> Row[] where each Row may contain Rows -> Row[].
    """
    if not isinstance(row_container, dict):
        return
    rows = row_container.get("Row")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        yield row
        nested = row.get("Rows")
        if isinstance(nested, dict):
            yield from _iter_rows(nested)


def _find_column_index(report: dict[str, Any], col_key: str) -> int | None:
    cols = report.get("Columns", {}).get("Column")
    if not isinstance(cols, list):
        return None
    for idx, col in enumerate(cols):
        if not isinstance(col, dict):
            continue
        meta = col.get("MetaData")
        if not isinstance(meta, list):
            continue
        for m in meta:
            if not isinstance(m, dict):
                continue
            if m.get("Name") == "ColKey" and m.get("Value") == col_key:
                return idx
    return None


# NOTE: account_type_map_from_accounts_payload moved to adapters.qbo.accounts


def balance_sheet_snapshot_from_report(
    report: dict[str, Any],
    *,
    realm_id: str | None = None,
    account_types: dict[str, QBOAccountTypeInfo] | None = None,
    include_rows_without_id: bool = True,
    include_summary_totals: bool = True,
) -> BalanceSheetSnapshot:
    """
    Convert a QBO Report Service BalanceSheet JSON payload into a BalanceSheetSnapshot.

    This function performs *no* network calls; it is intended to be used by an adapter layer.

    - Uses Header.EndPeriod as the snapshot as-of date.
    - Extracts only "Data" rows where the account column includes an `id` (QBO Account Id).
      Rows without an id (e.g., "Net Income") are excluded by default because they are not stable account identifiers.
    - If `include_summary_totals` is True, summary rows with labels containing "Total" are included as
      `report::Total ...` accounts.
    - Optionally enriches each account with type/subtype from a Chart of Accounts mapping.
      (Bank/CC inference in rules requires type/subtype to be present.)
    """
    if not isinstance(report, dict):
        raise QBOBalanceSheetAdapterError("Report payload must be a JSON object.")

    header = report.get("Header", {})
    if not isinstance(header, dict):
        raise QBOBalanceSheetAdapterError("Report.Header missing or invalid.")

    as_of = _parse_iso_date(header.get("EndPeriod"))
    if as_of is None:
        raise QBOBalanceSheetAdapterError("Report.Header.EndPeriod missing or not an ISO date (YYYY-MM-DD).")

    currency = header.get("Currency") if isinstance(header.get("Currency"), str) else "USD"

    account_col = _find_column_index(report, "account")
    total_col = _find_column_index(report, "total")
    # Fall back to the canonical sample structure if metadata is absent.
    account_col = 0 if account_col is None else account_col
    total_col = 1 if total_col is None else total_col

    accounts: list[dict[str, Any]] = []
    rows = report.get("Rows")
    if not isinstance(rows, dict):
        raise QBOBalanceSheetAdapterError("Report.Rows missing or invalid.")

    def _append_from_coldata(coldata: Any) -> None:
        if not isinstance(coldata, list):
            return
        if account_col >= len(coldata) or total_col >= len(coldata):
            return
        acct_cell = coldata[account_col]
        total_cell = coldata[total_col]
        if not isinstance(acct_cell, dict) or not isinstance(total_cell, dict):
            return
        acct_id = acct_cell.get("id")
        acct_name = acct_cell.get("value") if isinstance(acct_cell.get("value"), str) else ""
        if not isinstance(acct_id, str) or not acct_id.strip():
            if not include_rows_without_id:
                return
            acct_id = f"report::{acct_name}".strip() or "report::unknown"
        bal = _parse_decimal(total_cell.get("value"))
        if bal is None:
            return
        account_ref = acct_id.strip()
        if realm_id:
            account_ref = f"qbo::{realm_id}::{account_ref}"
        type_info = None
        if account_types and isinstance(acct_cell.get("id"), str):
            type_info = account_types.get(acct_cell["id"])
        accounts.append(
            {
                "account_ref": account_ref,
                "name": acct_name,
                "type": (type_info.account_type if type_info else "") or "",
                "subtype": (type_info.account_subtype if type_info else "") or "",
                "balance": str(bal),
            }
        )

    def _append_rows(row_container: dict[str, Any]) -> None:
        row_list = row_container.get("Row")
        if not isinstance(row_list, list):
            return
        for row in row_list:
            if not isinstance(row, dict):
                continue
            row_type = row.get("type")
            if row_type == "Data":
                _append_from_coldata(row.get("ColData"))
                continue

            header = row.get("Header")
            if isinstance(header, dict):
                _append_from_coldata(header.get("ColData"))

            nested = row.get("Rows")
            if isinstance(nested, dict):
                _append_rows(nested)

            if include_summary_totals and isinstance(row.get("Summary"), dict):
                summary = row["Summary"].get("ColData")
                if isinstance(summary, list):
                    acct_cell = summary[account_col] if account_col < len(summary) else None
                    acct_name = (
                        acct_cell.get("value")
                        if isinstance(acct_cell, dict) and isinstance(acct_cell.get("value"), str)
                        else ""
                    )
                    if "total" in (acct_name or "").lower():
                        _append_from_coldata(summary)

    _append_rows(rows)

    return BalanceSheetSnapshot(
        as_of_date=as_of,
        currency=currency,
        accounts=accounts,
    )
