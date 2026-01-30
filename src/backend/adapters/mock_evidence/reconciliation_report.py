from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from common.rules_engine.models import ReconciliationSnapshot


def reconciliation_snapshot_from_report(
    report: dict[str, Any],
    *,
    account_ref: str | None = None,
    source: str = "fixture",
) -> ReconciliationSnapshot:
    """
    Build a ReconciliationSnapshot from a JSON reconciliation report fixture.

    Expected (minimal) fields:
      - report["account"]["name"]
      - report["period"]["ending"] (statement end date)
      - report["summary"]["statement_ending_balance"]
      - report["summary"]["register_balance_as_of"]["date"|"balance"] (optional)

    Notes:
    - If account_ref is not provided, we use report["account"]["id"] when available,
      otherwise fall back to "name::<account_name>" for test fixtures.
    - book_balance_as_of_period_end is only set when register_balance_as_of.date
      matches period ending (strict).
    """
    account = report.get("account") or {}
    account_name = str(account.get("name") or "")
    resolved_account_ref = account_ref or account.get("id") or (
        f"name::{account_name}" if account_name else ""
    )
    if not resolved_account_ref:
        raise ValueError("Missing account_ref and account id/name in reconciliation report.")

    period = report.get("period") or {}
    summary = report.get("summary") or {}
    register = summary.get("register_balance_as_of") or {}

    period_end = _parse_date(period.get("ending"))
    register_date = _parse_date(register.get("date"))
    statement_end_date = period_end or register_date

    statement_ending_balance = _parse_decimal(summary.get("statement_ending_balance"))
    register_balance = _parse_decimal(register.get("balance"))

    book_balance_as_of_statement_end = register_balance or statement_ending_balance
    book_balance_as_of_period_end = (
        register_balance if register_date and period_end and register_date == period_end else None
    )

    return ReconciliationSnapshot(
        account_ref=str(resolved_account_ref),
        account_name=account_name,
        statement_end_date=statement_end_date,
        statement_ending_balance=statement_ending_balance,
        book_balance_as_of_statement_end=book_balance_as_of_statement_end,
        book_balance_as_of_period_end=book_balance_as_of_period_end,
        source=source,
        meta={
            "report_type": report.get("report", {}).get("type"),
            "reconciled_on": report.get("report", {}).get("reconciled_on"),
            "register_balance_as_of_date": register_date.isoformat() if register_date else None,
        },
    )


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))
