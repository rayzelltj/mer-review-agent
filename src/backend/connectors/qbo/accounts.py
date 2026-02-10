from __future__ import annotations

from typing import Any

from .client import qbo_get
from .config import QBOConfig


def fetch_accounts(config: QBOConfig) -> dict[str, Any]:
    """
    Fetch QBO Chart of Accounts (query endpoint).
    """
    query = "select * from Account"
    return qbo_get(
        config,
        f"/v3/company/{config.realm_id}/query",
        params={"query": query},
    )


def fetch_accounts_all(
    config: QBOConfig,
    *,
    max_results: int = 1000,
) -> dict[str, Any]:
    """
    Fetch QBO Chart of Accounts with basic pagination (query endpoint).
    """
    if max_results <= 0:
        raise ValueError("max_results must be > 0")

    start_position = 1
    all_accounts: list[dict[str, Any]] = []

    while True:
        query = (
            f"select * from Account startposition {start_position} maxresults {max_results}"
        )
        payload = qbo_get(
            config,
            f"/v3/company/{config.realm_id}/query",
            params={"query": query},
        )
        query_resp = payload.get("QueryResponse") if isinstance(payload, dict) else None
        accounts = []
        if isinstance(query_resp, dict):
            raw_accounts = query_resp.get("Account")
            if isinstance(raw_accounts, list):
                accounts = [a for a in raw_accounts if isinstance(a, dict)]
            elif isinstance(raw_accounts, dict):
                accounts = [raw_accounts]
        all_accounts.extend(accounts)

        if len(accounts) < max_results:
            break
        start_position += max_results

    return {"QueryResponse": {"Account": all_accounts}}
