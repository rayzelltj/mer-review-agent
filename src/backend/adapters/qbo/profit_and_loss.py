from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
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


@dataclass(frozen=True)
class ExpenseLineVariance:
    name: str
    current_amount: Decimal
    prior_amount: Decimal
    delta_amount: Decimal
    pct_change: Decimal | None
    abs_pct_change: Decimal | None
    is_new_activity: bool


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


def _extract_income_line_totals(
    report: dict[str, Any], *, group: str, total_col: int
) -> list[PnLTotal]:
    rows = report.get("Rows")
    if not isinstance(rows, dict):
        return []
    income_rows = None
    for row in rows.get("Row", []) if isinstance(rows.get("Row"), list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("group") == group:
            income_rows = row.get("Rows")
            break
    if not isinstance(income_rows, dict):
        return []

    totals: dict[str, Decimal] = {}
    for row in _iter_rows(income_rows):
        if row.get("type") != "Data":
            continue
        coldata = row.get("ColData")
        if not isinstance(coldata, list) or total_col >= len(coldata):
            continue
        name_cell = coldata[0]
        value_cell = coldata[total_col]
        if not isinstance(name_cell, dict) or not isinstance(value_cell, dict):
            continue
        name = (name_cell.get("value") or "").strip()
        if not name:
            continue
        value = _parse_decimal(value_cell.get("value"))
        if value is None:
            continue
        totals[name] = totals.get(name, Decimal("0")) + value

    return [PnLTotal(key=k, amount=v) for k, v in totals.items()]


def _extract_expense_line_variances(
    report: dict[str, Any], *, group: str, current_col: int, prior_col: int
) -> list[ExpenseLineVariance]:
    rows = report.get("Rows")
    if not isinstance(rows, dict):
        return []

    expense_rows = None
    for row in rows.get("Row", []) if isinstance(rows.get("Row"), list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("group") == group:
            expense_rows = row.get("Rows")
            break
    if not isinstance(expense_rows, dict):
        return []

    totals: dict[str, tuple[Decimal, Decimal]] = {}
    for row in _iter_rows(expense_rows):
        if row.get("type") != "Data":
            continue
        coldata = row.get("ColData")
        if not isinstance(coldata, list):
            continue
        if current_col >= len(coldata) or prior_col >= len(coldata):
            continue
        name_cell = coldata[0]
        current_cell = coldata[current_col]
        prior_cell = coldata[prior_col]
        if not isinstance(name_cell, dict) or not isinstance(current_cell, dict) or not isinstance(prior_cell, dict):
            continue
        name = str(name_cell.get("value") or "").strip()
        if not name:
            continue
        current_amount = _parse_decimal(current_cell.get("value"))
        prior_amount = _parse_decimal(prior_cell.get("value"))
        if current_amount is None and prior_amount is None:
            continue
        existing_current, existing_prior = totals.get(name, (Decimal("0"), Decimal("0")))
        totals[name] = (
            existing_current + (current_amount or Decimal("0")),
            existing_prior + (prior_amount or Decimal("0")),
        )

    out: list[ExpenseLineVariance] = []
    for name, (current_amount, prior_amount) in totals.items():
        delta_amount = current_amount - prior_amount
        if prior_amount == 0:
            pct_change = None
            abs_pct_change = None
            is_new_activity = current_amount != 0
        else:
            pct_change = delta_amount / abs(prior_amount)
            abs_pct_change = abs(pct_change)
            is_new_activity = False
        out.append(
            ExpenseLineVariance(
                name=name,
                current_amount=current_amount,
                prior_amount=prior_amount,
                delta_amount=delta_amount,
                pct_change=pct_change,
                abs_pct_change=abs_pct_change,
                is_new_activity=is_new_activity,
            )
        )
    out.sort(key=lambda item: abs(item.delta_amount), reverse=True)
    return out


def _prior_month_end(period_end: date) -> date:
    return period_end.replace(day=1) - timedelta(days=1)


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
    income_lines = _extract_income_line_totals(report, group=revenue_group, total_col=value_col)
    for item in income_lines:
        totals[f"income_line:{item.key}"] = item.amount

    return ProfitAndLossSnapshot(
        period_start=start,
        period_end=end,
        currency=currency,
        totals=totals,
    )


def expense_month_over_month_from_report(
    report: dict[str, Any],
    *,
    current_period_end: date | None = None,
) -> dict[str, Any]:
    """
    Extract month-over-month expense line variances from a QBO ProfitAndLoss report.

    The report must contain monthly columns (e.g., "Nov. 2025", "Dec. 2025")
    and an "Expenses" section. Output is intended for rules-engine evidence meta.
    """
    if not isinstance(report, dict):
        raise QBOProfitAndLossAdapterError("Report payload must be a JSON object.")

    header = report.get("Header", {})
    if not isinstance(header, dict):
        raise QBOProfitAndLossAdapterError("Report.Header missing or invalid.")

    end = _parse_iso_date(header.get("EndPeriod"))
    if end is None:
        raise QBOProfitAndLossAdapterError(
            "Report.Header.EndPeriod missing or not ISO date (YYYY-MM-DD)."
        )
    current_end = current_period_end or end
    prior_end = _prior_month_end(current_end)

    current_col = _find_month_column_index(report, current_end)
    if current_col is None:
        raise QBOProfitAndLossAdapterError(
            f"Monthly column for {current_end.strftime('%b %Y')} not found in report columns."
        )
    prior_col = _find_month_column_index(report, prior_end)
    if prior_col is None:
        raise QBOProfitAndLossAdapterError(
            f"Monthly column for {prior_end.strftime('%b %Y')} not found in report columns."
        )

    lines = _extract_expense_line_variances(
        report,
        group="Expenses",
        current_col=current_col,
        prior_col=prior_col,
    )

    return {
        "current_period_end": current_end.isoformat(),
        "prior_period_end": prior_end.isoformat(),
        "current_month_label": current_end.strftime("%b %Y"),
        "prior_month_label": prior_end.strftime("%b %Y"),
        "lines": [
            {
                "name": line.name,
                "current_amount": str(line.current_amount),
                "prior_amount": str(line.prior_amount),
                "delta_amount": str(line.delta_amount),
                "pct_change": str(line.pct_change) if line.pct_change is not None else None,
                "abs_pct_change": str(line.abs_pct_change) if line.abs_pct_change is not None else None,
                "is_new_activity": line.is_new_activity,
            }
            for line in lines
        ],
    }
