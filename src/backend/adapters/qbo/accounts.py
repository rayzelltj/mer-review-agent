from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class QBOAccountsAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class QBOAccountTypeInfo:
    account_type: str = ""
    account_subtype: str = ""


def account_type_map_from_accounts_payload(payload: Any) -> dict[str, QBOAccountTypeInfo]:
    """
    Build a mapping from QBO Account Id -> (AccountType, AccountSubType).

    Supports common QBO response shapes:
    - {"QueryResponse": {"Account": [ ... ]}}   (select * from Account)
    - {"Account": [ ... ]}                      (list)
    - {"Account": { ... }}                      (single account read)
    - [ { ... }, { ... } ]                      (raw list of accounts)
    """
    if not isinstance(payload, (dict, list)):
        raise QBOAccountsAdapterError("Accounts payload must be a JSON object or list of accounts.")

    accounts: list[dict[str, Any]] = []
    if isinstance(payload, list):
        accounts = [a for a in payload if isinstance(a, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("QueryResponse"), dict) and isinstance(
            payload["QueryResponse"].get("Account"), list
        ):
            accounts = [a for a in payload["QueryResponse"]["Account"] if isinstance(a, dict)]
        elif isinstance(payload.get("Account"), list):
            accounts = [a for a in payload["Account"] if isinstance(a, dict)]
        elif isinstance(payload.get("Account"), dict):
            accounts = [payload["Account"]]

    out: dict[str, QBOAccountTypeInfo] = {}
    for acct in accounts:
        acct_id = acct.get("Id")
        if not isinstance(acct_id, str) or not acct_id.strip():
            continue
        out[acct_id] = QBOAccountTypeInfo(
            account_type=str(acct.get("AccountType") or ""),
            account_subtype=str(acct.get("AccountSubType") or ""),
        )
    return out
