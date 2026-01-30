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
