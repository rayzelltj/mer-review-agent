from __future__ import annotations

from typing import Any

from .client import QBOHttpError, qbo_get
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


def fetch_trial_balance(
    config: QBOConfig,
    *,
    start_date: str,
    end_date: str,
    accounting_method: str = "Accrual",
) -> dict[str, Any]:
    """
    Fetch QBO Trial Balance report JSON.
    """
    return qbo_get(
        config,
        f"/v3/company/{config.realm_id}/reports/TrialBalance",
        params={
            "start_date": start_date,
            "end_date": end_date,
            "accounting_method": accounting_method,
        },
    )


def fetch_transaction_list_by_account(
    config: QBOConfig,
    *,
    account_id: str,
    start_date: str,
    end_date: str,
    accounting_method: str = "Accrual",
    include_split_detail: bool = True,
) -> dict[str, Any]:
    """
    Fetch QBO Transaction List by Account report JSON for one account.
    """
    params: dict[str, Any] = {
        "account": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "accounting_method": accounting_method,
    }
    # Some realms reject include_split_detail=true; only send when explicitly disabling splits.
    if not include_split_detail:
        params["include_split_detail"] = "false"

    try:
        return qbo_get(
            config,
            f"/v3/company/{config.realm_id}/reports/TransactionListByAccount",
            params=params,
        )
    except QBOHttpError as exc:
        # Some realms reject TransactionListByAccount or include_split_detail.
        if exc.status not in {400, 404}:
            raise
        fallback_params = dict(params)
        fallback_params.pop("include_split_detail", None)
        return qbo_get(
            config,
            f"/v3/company/{config.realm_id}/reports/TransactionList",
            params=fallback_params,
        )
