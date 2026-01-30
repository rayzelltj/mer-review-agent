from __future__ import annotations

from datetime import date

from adapters.qbo.pipeline import QBOAdapterOutputs, build_qbo_snapshots

from .accounts import fetch_accounts
from .config import QBOConfig
from .reports import fetch_balance_sheet, fetch_profit_and_loss


def build_snapshots(config: QBOConfig, *, period_end: date) -> QBOAdapterOutputs:
    """
    Orchestrate QBO fetchers + adapters to build canonical snapshots.

    Skeleton stub only. Should:
      - fetch Balance Sheet, P&L, Accounts JSON
      - call build_qbo_snapshots(...)
    """
    balance_sheet_report = fetch_balance_sheet(config, end_date=period_end.isoformat())
    pnl_start = _first_day_months_ago(period_end, 3)
    profit_and_loss_report = fetch_profit_and_loss(
        config,
        start_date=pnl_start.isoformat(),
        end_date=period_end.isoformat(),
        summarize_column_by="Month",
    )
    accounts_payload = fetch_accounts(config)
    return build_qbo_snapshots(
        balance_sheet_report=balance_sheet_report,
        profit_and_loss_report=profit_and_loss_report,
        accounts_payload=accounts_payload,
        realm_id=config.realm_id,
        pnl_summarize_by_month=True,
    )


def _first_day_months_ago(period_end: date, months_back: int) -> date:
    if months_back < 0:
        raise ValueError("months_back must be >= 0")
    year = period_end.year
    month = period_end.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)
