from __future__ import annotations

import csv
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common.rules_engine.models import EvidenceItem


class FixedAssetRegisterAdapterError(ValueError):
    pass


def fixed_asset_register_csv_to_evidence(
    csv_path: str | Path,
    *,
    period_end: date,
    source: str = "working_paper",
    uri: str | None = None,
    account_name_match: str | None = None,
) -> EvidenceItem:
    """
    Parse a single fixed asset register CSV (one asset class per file) and extract:
      - Closing Balance
      - Asset class name inferred from the filename
    """
    path = Path(csv_path)
    if not path.exists():
        raise FixedAssetRegisterAdapterError(f"Fixed asset register CSV not found: {path}")

    rows = _load_rows(path)
    closing_row = _find_row(rows, "Closing Balance")
    if closing_row is None or len(closing_row) < 2:
        raise FixedAssetRegisterAdapterError("Closing Balance row missing in fixed asset register CSV.")

    closing_balance = _parse_decimal(closing_row[1])
    if closing_balance is None:
        raise FixedAssetRegisterAdapterError("Closing Balance value is missing or invalid in fixed asset register CSV.")

    asset_class = _asset_class_from_filename(path)
    name_match = _clean_text(account_name_match) or asset_class

    return EvidenceItem(
        evidence_type="fixed_asset_register_balance",
        source=source,
        as_of_date=period_end,
        amount=closing_balance,
        uri=uri,
        meta={
            "working_paper_type": "fixed_asset_register",
            "asset_class": asset_class,
            "account_name_match": name_match,
            "closing_balance_as_per_register": str(closing_balance),
        },
    )


def depreciation_schedule_to_evidence(
    csv_path: str | Path,
    *,
    period_end: date,
    source: str = "working_paper",
    uri: str | None = None,
) -> EvidenceItem:
    """
    Parse a depreciation/fixed-asset continuity schedule and extract
    'Closing Balance as per register' per asset class for the target month column.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FixedAssetRegisterAdapterError(f"Depreciation schedule CSV not found: {path}")

    rows = _load_rows(path)
    header, header_idx = _find_header_row(rows)
    if header is None or header_idx is None:
        raise FixedAssetRegisterAdapterError("Header row with 'Asset Class' not found in depreciation schedule.")

    month_label, month_idx = _find_month_column(header, period_end)
    if month_idx is None or month_label is None:
        raise FixedAssetRegisterAdapterError(
            f"Month column for {period_end.isoformat()} not found in depreciation schedule."
        )

    items: list[dict[str, Any]] = []
    current_asset_class = ""
    for row in rows[header_idx + 1 :]:
        if not row:
            continue
        asset_class_cell = _cell_at(row, 0)
        purpose_cell = _cell_at(row, 1)
        purpose_norm = _normalize_text(purpose_cell)

        if asset_class_cell and purpose_norm == "opening balance":
            current_asset_class = asset_class_cell

        if not purpose_norm.startswith("closing balance as per register"):
            continue

        asset_class = current_asset_class or asset_class_cell
        if not asset_class:
            continue
        if month_idx >= len(row):
            continue

        amount = _parse_decimal(row[month_idx])
        if amount is None:
            continue

        cleaned_asset_class = _strip_account_code(asset_class)
        account_name_match = cleaned_asset_class.split(" - ", 1)[0].strip() or cleaned_asset_class
        items.append(
            {
                "asset_class": cleaned_asset_class,
                "account_name_match": account_name_match,
                "balance": str(amount),
            }
        )

    if not items:
        raise FixedAssetRegisterAdapterError(
            f"No 'Closing Balance as per register' values found for '{month_label}' in depreciation schedule."
        )

    return EvidenceItem(
        evidence_type="fixed_asset_register_balance",
        source=source,
        as_of_date=period_end,
        uri=uri,
        meta={
            "working_paper_type": "depreciation_schedule",
            "month_label": month_label,
            "items": items,
        },
    )


def _load_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as handle:
        return list(csv.reader(handle))


def _find_row(rows: list[list[str]], key: str) -> list[str] | None:
    key_norm = _normalize_text(key)
    for row in rows:
        if not row:
            continue
        if _normalize_text(_cell_at(row, 0)) == key_norm:
            return row
    return None


def _find_header_row(rows: list[list[str]]) -> tuple[list[str] | None, int | None]:
    for idx, row in enumerate(rows):
        if not row:
            continue
        if _normalize_text(_cell_at(row, 0)) == "asset class":
            return row, idx
    return None, None


def _find_month_column(header: list[str], period_end: date) -> tuple[str | None, int | None]:
    wanted_labels = {
        _normalize_text(period_end.strftime("%d %b %Y")),
        _normalize_text(f"{period_end.day} {period_end.strftime('%b %Y')}"),
        _normalize_text(period_end.strftime("%d %B %Y")),
        _normalize_text(f"{period_end.day} {period_end.strftime('%B %Y')}"),
    }
    for idx, cell in enumerate(header):
        norm = _normalize_text(cell)
        if norm in wanted_labels:
            return _clean_text(cell), idx
    return None, None


def _asset_class_from_filename(path: Path) -> str:
    stem = path.stem
    match = re.search(r"fixed asset register\s*-\s*(.+)$", stem, flags=re.IGNORECASE)
    if match:
        return _clean_text(match.group(1))
    return _clean_text(stem)


def _strip_account_code(value: str) -> str:
    return re.sub(r"^\d+\s*", "", _clean_text(value)).strip()


def _cell_at(row: list[str], idx: int) -> str:
    if idx >= len(row):
        return ""
    return _clean_text(row[idx])


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\u00a0", " ").strip()


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean_text(value).lower())


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = _clean_text(value).replace(",", "").replace("$", "").strip()
        if not s or s in {"-", "--", "- -"}:
            return None
        if s.startswith("(") and s.endswith(")"):
            s = f"-{s[1:-1].strip()}"
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None
