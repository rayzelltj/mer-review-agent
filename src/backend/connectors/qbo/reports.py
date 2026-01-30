from __future__ import annotations

from typing import Any

from .client import qbo_get
from .config import QBOConfig


def fetch_balance_sheet(
    config: QBOConfig,
    *,
    end_date: str,
    accounting_method: str = "Accrual",
) -> dict[str, Any]:
    """
    Fetch QBO Balance Sheet report JSON.
    """
    return qbo_get(
        config,
        f"/v3/company/{config.realm_id}/reports/BalanceSheet",
        params={
            "end_date": end_date,
            "accounting_method": accounting_method,
        },
    )


def fetch_profit_and_loss(
    config: QBOConfig,
    *,
    start_date: str,
    end_date: str,
    accounting_method: str = "Accrual",
    summarize_column_by: str | None = None,
) -> dict[str, Any]:
    """
    Fetch QBO Profit and Loss report JSON.
    """
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "accounting_method": accounting_method,
    }
    if summarize_column_by:
        params["summarize_column_by"] = summarize_column_by

    return qbo_get(
        config,
        f"/v3/company/{config.realm_id}/reports/ProfitAndLoss",
        params=params,
    )
