from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal

from common.rules_engine.models import EvidenceItem


class QBOAgingReportAdapterError(ValueError):
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
        s = value.strip().replace(",", "")
        if not s:
            return None
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


def _find_column_indices(report: dict[str, Any]) -> dict[str, int]:
    cols = report.get("Columns", {}).get("Column")
    if not isinstance(cols, list):
        return {}

    idx_by_key: dict[str, int] = {}
    idx_by_title: dict[str, int] = {}
    for idx, col in enumerate(cols):
        if not isinstance(col, dict):
            continue
        title = str(col.get("ColTitle") or "").strip().lower()
        if title:
            idx_by_title[title] = idx
        meta = col.get("MetaData")
        if isinstance(meta, list):
            for m in meta:
                if not isinstance(m, dict):
                    continue
                if m.get("Name") == "ColKey":
                    idx_by_key[str(m.get("Value") or "")] = idx

    # Normalize to canonical labels.
    out: dict[str, int] = {}
    out["current"] = idx_by_key.get("current", idx_by_title.get("current", -1))
    out["1_30"] = idx_by_key.get("0", idx_by_title.get("1 - 30", -1))
    out["31_60"] = idx_by_key.get("1", idx_by_title.get("31 - 60", -1))
    out["61_90"] = idx_by_key.get("2", idx_by_title.get("61 - 90", -1))
    out["91_over"] = idx_by_key.get("3", idx_by_title.get("91 and over", -1))
    out["total"] = idx_by_key.get("total", idx_by_title.get("total", -1))
    out["name"] = idx_by_title.get("", 0)
    return out


def _get_cell_value(coldata: list[dict[str, Any]], idx: int) -> Decimal:
    if idx < 0 or idx >= len(coldata):
        return Decimal("0")
    cell = coldata[idx]
    if not isinstance(cell, dict):
        return Decimal("0")
    value = _parse_decimal(cell.get("value"))
    return value if value is not None else Decimal("0")


def _get_name(coldata: list[dict[str, Any]], idx: int) -> str:
    if idx < 0 or idx >= len(coldata):
        return ""
    cell = coldata[idx]
    if not isinstance(cell, dict):
        return ""
    return str(cell.get("value") or "").strip()


def _parse_header_as_of(report: dict[str, Any]) -> date | None:
    header = report.get("Header", {})
    if not isinstance(header, dict):
        return None
    as_of = _parse_iso_date(header.get("EndPeriod"))
    if as_of is not None:
        return as_of
    options = header.get("Option")
    if isinstance(options, list):
        for opt in options:
            if isinstance(opt, dict) and opt.get("Name") == "report_date":
                return _parse_iso_date(opt.get("Value"))
    return None


def _extract_aging_report_rows(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise QBOAgingReportAdapterError("Report payload must be a JSON object.")

    rows = report.get("Rows")
    if not isinstance(rows, dict):
        raise QBOAgingReportAdapterError("Report.Rows missing or invalid.")

    idx = _find_column_indices(report)
    out_rows: list[dict[str, Any]] = []
    grand_total: dict[str, Decimal] | None = None

    for row in _iter_rows(rows):
        if row.get("group") == "GrandTotal" and isinstance(row.get("Summary"), dict):
            summary = row["Summary"].get("ColData")
            if isinstance(summary, list):
                grand_total = {
                    "current": _get_cell_value(summary, idx["current"]),
                    "1_30": _get_cell_value(summary, idx["1_30"]),
                    "31_60": _get_cell_value(summary, idx["31_60"]),
                    "61_90": _get_cell_value(summary, idx["61_90"]),
                    "91_over": _get_cell_value(summary, idx["91_over"]),
                    "total": _get_cell_value(summary, idx["total"]),
                }
            continue

        coldata = row.get("ColData")
        if not isinstance(coldata, list):
            continue
        name = _get_name(coldata, idx["name"])
        if not name:
            continue
        row_data = {
            "name": name,
            "current": _get_cell_value(coldata, idx["current"]),
            "1_30": _get_cell_value(coldata, idx["1_30"]),
            "31_60": _get_cell_value(coldata, idx["31_60"]),
            "61_90": _get_cell_value(coldata, idx["61_90"]),
            "91_over": _get_cell_value(coldata, idx["91_over"]),
            "total": _get_cell_value(coldata, idx["total"]),
        }
        out_rows.append(row_data)

    return {"rows": out_rows, "grand_total": grand_total}


def aging_report_to_evidence(
    report: dict[str, Any],
    *,
    report_type: Literal["ap", "ar"],
    report_kind: Literal["summary", "detail"],
) -> list[EvidenceItem]:
    """
    Convert a QBO Aged Payables/Receivables report into EvidenceItems:
      - <type>_aging_<kind>_total: grand total 'Total' column
      - <type>_aging_<kind>_over_60: grand total of 61-90 + 91+ columns, with item-level meta
    """
    as_of = _parse_header_as_of(report)
    if as_of is None:
        raise QBOAgingReportAdapterError("Report.Header.EndPeriod/report_date missing or invalid.")

    currency = None
    header = report.get("Header", {})
    if isinstance(header, dict) and isinstance(header.get("Currency"), str):
        currency = header.get("Currency")

    parsed = _extract_aging_report_rows(report)
    rows = parsed["rows"]
    grand = parsed["grand_total"]

    if grand is None:
        raise QBOAgingReportAdapterError("GrandTotal summary row missing in aging report.")

    over_60_total = grand["61_90"] + grand["91_over"]

    items_over_60: list[dict[str, Any]] = []
    for r in rows:
        over_amt = r["61_90"] + r["91_over"]
        if over_amt == 0:
            continue
        items_over_60.append(
            {
                "name": r["name"],
                "amount": str(over_amt),
                "age_bucket": "over_60",
                "over_threshold": True,
                "age_bucket_amounts": {
                    "61_90": str(r["61_90"]),
                    "91_over": str(r["91_over"]),
                },
            }
        )

    prefix = "ap" if report_type == "ap" else "ar"
    total_type = f"{prefix}_aging_{report_kind}_total"
    over_type = f"{prefix}_aging_{report_kind}_over_60"
    rows_type = f"{prefix}_aging_{report_kind}_rows"

    total_item = EvidenceItem(
        evidence_type=total_type,
        source="qbo_report",
        as_of_date=as_of,
        amount=str(grand["total"]),
        meta={"currency": currency} if currency else {},
    )
    over_item = EvidenceItem(
        evidence_type=over_type,
        source="qbo_report",
        as_of_date=as_of,
        amount=str(over_60_total),
        meta={
            "currency": currency,
            "items": items_over_60,
            "age_threshold_days": 60,
        },
    )

    items = [total_item, over_item]

    if report_kind == "detail":
        detail_items = []
        for r in rows:
            detail_items.append(
                {
                    "name": r["name"],
                    "open_balance": str(r["total"]),
                    "current": str(r["current"]),
                    "1_30": str(r["1_30"]),
                    "31_60": str(r["31_60"]),
                    "61_90": str(r["61_90"]),
                    "91_over": str(r["91_over"]),
                }
            )
        items.append(
            EvidenceItem(
                evidence_type=rows_type,
                source="qbo_report",
                as_of_date=as_of,
                amount=str(grand["total"]),
                meta={"currency": currency, "items": detail_items},
            )
        )

    return items
