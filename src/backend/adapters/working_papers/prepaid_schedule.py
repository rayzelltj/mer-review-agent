from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common.rules_engine.models import EvidenceItem


class WorkingPaperAdapterError(ValueError):
    pass


def prepaid_schedule_to_evidence(
    csv_path: str | Path,
    *,
    period_end: date,
    source: str = "working_paper",
    uri: str | None = None,
) -> EvidenceItem:
    """
    Parse a Prepaid Schedule CSV export and extract the Balance at EOM (calculated)
    for the specified period_end month.
    """
    path = Path(csv_path)
    if not path.exists():
        raise WorkingPaperAdapterError(f"Prepaid schedule CSV not found: {path}")

    rows = _load_rows(path)
    header_row, header_idx = _find_header_row(rows)
    if header_row is None or header_idx is None:
        raise WorkingPaperAdapterError("Header row with month columns not found in prepaid schedule.")

    target_label = period_end.strftime("%b %Y")
    month_idx = _find_column_index(header_row, target_label)
    if month_idx is None:
        raise WorkingPaperAdapterError(
            f"Month column '{target_label}' not found in prepaid schedule header."
        )

    balance_row = _find_balance_row(rows)
    if balance_row is None:
        raise WorkingPaperAdapterError(
            "Row 'Balance at EOM (calculated)' not found in prepaid schedule."
        )
    if month_idx >= len(balance_row):
        raise WorkingPaperAdapterError(
            f"Month column '{target_label}' missing from balance row."
        )

    amount = _parse_decimal(balance_row[month_idx])
    if amount is None:
        raise WorkingPaperAdapterError(
            f"Balance at EOM amount missing or invalid for '{target_label}'."
        )

    return EvidenceItem(
        evidence_type="working_paper_balance",
        source=source,
        as_of_date=period_end,
        amount=amount,
        uri=uri,
        meta={
            "working_paper_type": "prepaid_schedule",
            "working_paper_row": "Balance at EOM (calculated)",
            "month_label": target_label,
        },
    )


def _load_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as handle:
        return list(csv.reader(handle))


def _find_header_row(rows: list[list[str]]) -> tuple[list[str] | None, int | None]:
    for idx, row in enumerate(rows):
        if not row:
            continue
        if _cell_eq(row[0], "Name"):
            return row, idx
    return None, None


def _find_balance_row(rows: list[list[str]]) -> list[str] | None:
    for row in rows:
        if any(_cell_eq(cell, "Balance at EOM (calculated)") for cell in row):
            return row
    return None


def _find_column_index(row: list[str], label: str) -> int | None:
    for idx, cell in enumerate(row):
        if _cell_eq(cell, label):
            return idx
    return None


def _cell_eq(value: Any, expected: str) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() == expected.strip().lower()


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
        s = s.replace(",", "").replace("$", "")
        s = s.replace("\u00a0", "").strip()
        if s.startswith("(") and s.endswith(")"):
            s = f"-{s[1:-1].strip()}"
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None
