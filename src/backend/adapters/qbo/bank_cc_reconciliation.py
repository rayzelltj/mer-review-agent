from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def account_ref_for_qbo_id(account_id: str, *, realm_id: str | None = None) -> str:
    raw = str(account_id or "").strip()
    if not raw:
        return ""
    if realm_id:
        return f"qbo::{realm_id}::{raw}"
    return raw


def active_bank_cc_accounts_from_accounts_payload(
    payload: Any,
    *,
    realm_id: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    accounts = _select_accounts(payload)
    out: list[dict[str, Any]] = []
    for acct in accounts:
        account_id = str(acct.get("Id") or "").strip()
        if not account_id:
            continue
        account_type = str(acct.get("AccountType") or "").strip()
        if account_type not in {"Bank", "Credit Card"}:
            continue
        active = acct.get("Active") is not False
        if active_only and not active:
            continue
        out.append(
            {
                "account_ref": account_ref_for_qbo_id(account_id, realm_id=realm_id),
                "account_id": account_id,
                "account_name": str(acct.get("Name") or "").strip(),
                "account_type": account_type,
                "account_subtype": str(acct.get("AccountSubType") or "").strip(),
                "classification": str(acct.get("Classification") or "").strip(),
                "active": active,
                "parent_account_id": str((acct.get("ParentRef") or {}).get("value") or "").strip() or None,
                "fully_qualified_name": str(acct.get("FullyQualifiedName") or "").strip(),
            }
        )
    return sorted(out, key=lambda row: str(row.get("account_ref") or ""))


def trial_balance_register_balances_from_report(
    payload: Any,
    *,
    realm_id: str | None = None,
) -> dict[str, Decimal]:
    report = coerce_report_payload(payload)
    if not isinstance(report, dict):
        return {}

    account_col = _find_column_index_by_hints(report, hints=("account",))
    debit_col = _find_column_index_by_hints(report, hints=("debit",))
    credit_col = _find_column_index_by_hints(report, hints=("credit",))
    account_col = 0 if account_col is None else account_col
    debit_col = 1 if debit_col is None else debit_col
    credit_col = 2 if credit_col is None else credit_col

    out: dict[str, Decimal] = {}
    rows = report.get("Rows")
    for row in _iter_rows(rows):
        coldata = row.get("ColData")
        if not isinstance(coldata, list):
            continue
        if account_col >= len(coldata):
            continue
        acct_cell = coldata[account_col]
        if not isinstance(acct_cell, dict):
            continue
        account_id = str(acct_cell.get("id") or "").strip()
        if not account_id:
            continue
        debit = _cell_amount_at(coldata, debit_col)
        credit = _cell_amount_at(coldata, credit_col)
        if debit is None and credit is None:
            continue
        net = (debit or Decimal("0")) - (credit or Decimal("0"))
        account_ref = account_ref_for_qbo_id(account_id, realm_id=realm_id)
        out[account_ref] = out.get(account_ref, Decimal("0")) + net
    return out


def transaction_list_unreconciled_sums_from_report(
    payload: Any,
    *,
    period_end: date,
    statement_end_date: date | None = None,
) -> dict[str, Any]:
    report = coerce_report_payload(payload)
    target_account_id = _extract_account_id(payload)
    if not isinstance(report, dict):
        return {
            "sum_not_reconciled_as_of_period_end": Decimal("0"),
            "sum_not_reconciled_between_period_end_and_statement_end": Decimal("0"),
            "clear_status_column_found": False,
            "parsed_rows": 0,
            "ignored_rows": 0,
            "account_id": target_account_id,
        }

    amount_col = _find_column_index_by_hints(report, hints=("amount", "amt"))
    date_col = _find_column_index_by_hints(report, hints=("date",))
    account_col = _find_column_index_by_hints(report, hints=("account",))
    clear_col = _find_column_index_by_hints(
        report,
        hints=("clr", "clear", "recon", "rstatus", "status"),
    )

    s1 = Decimal("0")
    s2 = Decimal("0")
    parsed_rows = 0
    ignored_rows = 0
    statement_end = statement_end_date or period_end

    rows = report.get("Rows")
    for row in _iter_rows(rows):
        coldata = row.get("ColData")
        if not isinstance(coldata, list):
            continue

        if target_account_id and not _row_matches_account(coldata, target_account_id, account_col):
            continue

        txn_date = _cell_date(coldata, date_col)
        amount = _cell_amount(coldata, amount_col)
        if txn_date is None or amount is None:
            ignored_rows += 1
            continue

        clear_value = _cell_text(coldata, clear_col).strip().upper() if clear_col is not None else ""
        is_unreconciled = _is_unreconciled_status(clear_value)
        parsed_rows += 1
        if not is_unreconciled:
            continue

        if txn_date <= period_end:
            s1 += amount
        elif period_end < txn_date <= statement_end:
            s2 += amount

    return {
        "sum_not_reconciled_as_of_period_end": s1,
        "sum_not_reconciled_between_period_end_and_statement_end": s2,
        "clear_status_column_found": clear_col is not None,
        "parsed_rows": parsed_rows,
        "ignored_rows": ignored_rows,
        "account_id": target_account_id,
    }


def coerce_report_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict) and isinstance(payload.get("Header"), dict) and isinstance(
        payload.get("Rows"), dict
    ):
        return payload
    if isinstance(payload, dict):
        nested = payload.get("payload")
        if isinstance(nested, dict):
            return coerce_report_payload(nested)
        report = payload.get("report")
        if isinstance(report, dict):
            return coerce_report_payload(report)
    return None


def _extract_account_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    extra = payload.get("extra")
    if isinstance(extra, dict):
        account_id = str(extra.get("account_id") or "").strip()
        if account_id:
            return account_id
    params = payload.get("params")
    if isinstance(params, dict):
        account_id = str(params.get("account") or "").strip()
        if account_id:
            return account_id
    return None


def _select_accounts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    query = payload.get("QueryResponse")
    if isinstance(query, dict) and isinstance(query.get("Account"), list):
        return [row for row in query["Account"] if isinstance(row, dict)]
    if isinstance(payload.get("Account"), list):
        return [row for row in payload["Account"] if isinstance(row, dict)]
    if isinstance(payload.get("Account"), dict):
        return [payload["Account"]]
    return []


def _iter_rows(row_container: Any):
    if not isinstance(row_container, dict):
        return
    rows = row_container.get("Row")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("ColData"), list):
            yield row
        nested = row.get("Rows")
        if isinstance(nested, dict):
            yield from _iter_rows(nested)


def _find_column_index_by_hints(report: dict[str, Any], *, hints: tuple[str, ...]) -> int | None:
    columns = report.get("Columns")
    if not isinstance(columns, dict):
        return None
    col_list = columns.get("Column")
    if not isinstance(col_list, list):
        return None
    lowered_hints = tuple(h.lower() for h in hints)
    for idx, col in enumerate(col_list):
        if not isinstance(col, dict):
            continue

        parts: list[str] = []
        col_title = str(col.get("ColTitle") or "").strip().lower()
        if col_title:
            parts.append(col_title)

        meta = col.get("MetaData")
        if isinstance(meta, list):
            for item in meta:
                if not isinstance(item, dict):
                    continue
                value = str(item.get("Value") or "").strip().lower()
                if value:
                    parts.append(value)
        haystack = " ".join(parts)
        if any(h in haystack for h in lowered_hints):
            return idx
    return None


def _row_matches_account(coldata: list[Any], target_account_id: str, account_col: int | None) -> bool:
    target = str(target_account_id or "").strip()
    if not target:
        return True
    if account_col is not None:
        cell_id = _cell_id(coldata, account_col)
        if cell_id:
            return cell_id == target
    for cell in coldata:
        if not isinstance(cell, dict):
            continue
        cell_id = str(cell.get("id") or "").strip()
        if cell_id and cell_id == target:
            return True
    return False


def _cell_text(coldata: list[Any], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(coldata):
        return ""
    cell = coldata[idx]
    if not isinstance(cell, dict):
        return ""
    return str(cell.get("value") or "")


def _cell_id(coldata: list[Any], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(coldata):
        return ""
    cell = coldata[idx]
    if not isinstance(cell, dict):
        return ""
    return str(cell.get("id") or "").strip()


def _cell_amount(coldata: list[Any], idx: int | None) -> Decimal | None:
    if idx is not None:
        value = _cell_amount_at(coldata, idx)
        if value is not None:
            return value
    for cell in coldata:
        if not isinstance(cell, dict):
            continue
        value = _parse_decimal(cell.get("value"))
        if value is not None:
            return value
    return None


def _cell_amount_at(coldata: list[Any], idx: int | None) -> Decimal | None:
    if idx is None or idx < 0 or idx >= len(coldata):
        return None
    cell = coldata[idx]
    if not isinstance(cell, dict):
        return None
    return _parse_decimal(cell.get("value"))


def _cell_date(coldata: list[Any], idx: int | None) -> date | None:
    if idx is not None:
        parsed = _parse_date(_cell_text(coldata, idx))
        if parsed is not None:
            return parsed
    for cell in coldata:
        if not isinstance(cell, dict):
            continue
        parsed = _parse_date(cell.get("value"))
        if parsed is not None:
            return parsed
    return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return -abs(number) if negative else number


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _is_unreconciled_status(value: str) -> bool:
    status = (value or "").strip().upper()
    if status in {"", "C", "CLEARED"}:
        return True
    if "NOT RECONCILED" in status:
        return True
    if status in {"R", "RECONCILED"}:
        return False
    # Conservative fallback: treat unknown status as unreconciled so it surfaces for review.
    return True
