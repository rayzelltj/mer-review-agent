from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from common.rules_engine.models import ProfitAndLossSnapshot


class QBOProfitAndLossAdapterError(ValueError):
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
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        s = s.replace(",", "")
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def _iter_rows(row_container: Any) -> Iterable[dict[str, Any]]:
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


def _find_month_column_index(report: dict[str, Any], period_end: date) -> int | None:
    cols = report.get("Columns", {}).get("Column")
    if not isinstance(cols, list):
        return None
    target_year = str(period_end.year)
    short = calendar.month_abbr[period_end.month]
    long = calendar.month_name[period_end.month]
    patterns = [
        re.compile(rf"^{re.escape(short)}\.?\s+{target_year}$", re.IGNORECASE),
        re.compile(rf"^{re.escape(long)}\s+{target_year}$", re.IGNORECASE),
    ]
    for idx, col in enumerate(cols):
        if not isinstance(col, dict):
            continue
        title = col.get("ColTitle")
        if not isinstance(title, str):
            continue
        title = title.strip()
        if not title:
            continue
        if any(p.match(title) for p in patterns):
            return idx
    return None


@dataclass(frozen=True)
class PnLTotal:
    key: str
    amount: Decimal


def _extract_total_by_group(
    report: dict[str, Any], *, group: str, total_col: int
) -> Decimal | None:
    rows = report.get("Rows")
    if not isinstance(rows, dict):
        return None
    for row in _iter_rows(rows):
        if row.get("group") != group:
            continue
        summary = row.get("Summary")
        if not isinstance(summary, dict):
            continue
        coldata = summary.get("ColData")
        if not isinstance(coldata, list) or total_col >= len(coldata):
            continue
        cell = coldata[total_col]
        if not isinstance(cell, dict):
            continue
        return _parse_decimal(cell.get("value"))
    return None


def _extract_total_by_label(
    report: dict[str, Any], *, label: str, total_col: int
) -> Decimal | None:
    rows = report.get("Rows")
    if not isinstance(rows, dict):
        return None
    for row in _iter_rows(rows):
        summary = row.get("Summary")
        if not isinstance(summary, dict):
            continue
        coldata = summary.get("ColData")
        if not isinstance(coldata, list) or total_col >= len(coldata):
            continue
        first = coldata[0]
        if not isinstance(first, dict):
            continue
        if (first.get("value") or "").strip().lower() != label.strip().lower():
            continue
        cell = coldata[total_col]
        if not isinstance(cell, dict):
            continue
        return _parse_decimal(cell.get("value"))
    return None


def profit_and_loss_snapshot_from_report(
    report: dict[str, Any],
    *,
    revenue_group: str = "Income",
    revenue_label: str = "Total Income",
    summarize_by_month: bool = False,
) -> ProfitAndLossSnapshot:
    """
    Convert a QBO Report Service ProfitAndLoss JSON payload into a ProfitAndLossSnapshot.

    - Uses Header.StartPeriod/EndPeriod for period range
    - Extracts revenue total from the Income section summary (group == "Income")
      with a fallback to a summary label "Total Income" if group is missing.
    """
    if not isinstance(report, dict):
        raise QBOProfitAndLossAdapterError("Report payload must be a JSON object.")

    header = report.get("Header", {})
    if not isinstance(header, dict):
        raise QBOProfitAndLossAdapterError("Report.Header missing or invalid.")

    start = _parse_iso_date(header.get("StartPeriod"))
    end = _parse_iso_date(header.get("EndPeriod"))
    if start is None or end is None:
        raise QBOProfitAndLossAdapterError(
            "Report.Header.StartPeriod or EndPeriod missing or not ISO date (YYYY-MM-DD)."
        )

    currency = header.get("Currency") if isinstance(header.get("Currency"), str) else "USD"

    total_col = _find_column_index(report, "total")
    total_col = 1 if total_col is None else total_col
    value_col = total_col

    if summarize_by_month:
        month_col = _find_month_column_index(report, end)
        if month_col is None:
            raise QBOProfitAndLossAdapterError(
                f"Monthly column for {end.strftime('%b %Y')} not found in report columns."
            )
        value_col = month_col

    revenue = _extract_total_by_group(report, group=revenue_group, total_col=value_col)
    if revenue is None:
        revenue = _extract_total_by_label(report, label=revenue_label, total_col=value_col)

    totals: dict[str, Decimal] = {}
    if revenue is not None:
        totals["revenue"] = revenue

    return ProfitAndLossSnapshot(
        period_start=start,
        period_end=end,
        currency=currency,
        totals=totals,
    )
