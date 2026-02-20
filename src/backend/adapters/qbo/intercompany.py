from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from common.rules_engine.models import EvidenceItem


class QBOIntercompanyAdapterError(ValueError):
    pass


def intercompany_balance_sheets_to_evidence(
    payload: dict[str, Any],
    *,
    as_of_date: date | None = None,
    source: str = "qbo",
) -> EvidenceItem:
    """
    Convert counterparty balance sheet payloads into a single EvidenceItem.

    Expected minimal fixture shape:
      {
        "as_of_date": "YYYY-MM-DD",
        "items": [
          {"company": "...", "counterparty": "...", "balance": "123.45", "account_name": "...", "account_ref": "..."}
        ]
      }
    """
    if not isinstance(payload, dict):
        raise QBOIntercompanyAdapterError(
            "Intercompany balance sheet payload must be a JSON object."
        )

    evidence_as_of = as_of_date or _parse_date(payload.get("as_of_date"))

    items_raw = payload.get("items")
    if items_raw is None:
        items_raw = payload.get("balances") or payload.get("intercompany") or []
    if not isinstance(items_raw, list):
        raise QBOIntercompanyAdapterError(
            "Intercompany balance sheet items must be a list."
        )

    items: list[dict[str, Any]] = []
    for entry in items_raw:
        if not isinstance(entry, dict):
            continue
        balance = _parse_decimal(entry.get("balance") or entry.get("amount"))
        items.append(
            {
                "company": str(entry.get("company") or entry.get("entity") or "").strip(),
                "counterparty": str(
                    entry.get("counterparty")
                    or entry.get("company")
                    or entry.get("entity")
                    or ""
                ).strip(),
                "balance": balance,
                "account_name": str(entry.get("account_name") or "").strip(),
                "account_ref": str(entry.get("account_ref") or "").strip(),
            }
        )

    return EvidenceItem(
        evidence_type="intercompany_balance_sheet",
        source=source,
        as_of_date=evidence_as_of,
        meta={"items": items},
    )


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            return None
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None
