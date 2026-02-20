from __future__ import annotations

from typing import Any, Sequence

from .config import QBOConfig
from .reports import fetch_balance_sheet


def fetch_counterparty_balance_sheets(
    *,
    counterparty_configs: Sequence[QBOConfig],
    end_date: str,
    accounting_method: str = "Accrual",
) -> list[dict[str, Any]]:
    """Fetch BalanceSheet report payloads for each counterparty realm."""
    payloads: list[dict[str, Any]] = []
    for config in counterparty_configs:
        payloads.append(
            fetch_balance_sheet(
                config,
                end_date=end_date,
                accounting_method=accounting_method,
            )
        )
    return payloads
