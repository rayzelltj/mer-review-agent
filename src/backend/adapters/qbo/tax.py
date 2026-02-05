from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from common.rules_engine.models import EvidenceItem


class QBOTaxAdapterError(ValueError):
    pass


def tax_agencies_to_evidence(agencies: list[dict[str, Any]]) -> EvidenceItem:
    items = []
    for agency in agencies:
        if not isinstance(agency, dict):
            continue
        items.append(
            {
                "id": str(agency.get("Id") or "").strip(),
                "display_name": agency.get("DisplayName") or "",
                "last_file_date": _parse_date(agency.get("LastFileDate")),
                "tax_tracked_on_sales": bool(agency.get("TaxTrackedOnSales")),
                "tax_tracked_on_purchases": bool(agency.get("TaxTrackedOnPurchases")),
            }
        )
    return EvidenceItem(
        evidence_type="tax_agencies",
        source="qbo",
        meta={"items": items},
    )


def tax_returns_to_evidence(returns: list[dict[str, Any]]) -> EvidenceItem:
    items = []
    for ret in returns:
        if not isinstance(ret, dict):
            continue
        agency_ref = ret.get("AgencyRef") or {}
        items.append(
            {
                "id": str(ret.get("Id") or "").strip(),
                "agency_id": str(agency_ref.get("value") or "").strip(),
                "start_date": _parse_date(ret.get("StartDate")),
                "end_date": _parse_date(ret.get("EndDate")),
                "file_date": _parse_date(ret.get("FileDate")),
                "net_tax_amount_due": _parse_decimal(ret.get("NetTaxAmountDue")),
                "upcoming_filing": bool(ret.get("UpcomingFiling")),
            }
        )
    return EvidenceItem(
        evidence_type="tax_returns",
        source="qbo",
        meta={"items": items},
    )


def tax_payments_to_evidence(payments: list[dict[str, Any]]) -> EvidenceItem:
    items = []
    for payment in payments:
        if not isinstance(payment, dict):
            continue
        items.append(
            {
                "id": str(payment.get("Id") or "").strip(),
                "agency_id": str((payment.get("AgencyRef") or {}).get("value") or "").strip()
                or None,
                "payment_date": _parse_date(payment.get("PaymentDate")),
                "payment_amount": _parse_decimal(payment.get("PaymentAmount")),
                "refund": bool(payment.get("Refund")),
                "payment_account_name": (
                    (payment.get("PaymentAccountRef") or {}).get("name") or ""
                ),
            }
        )
    return EvidenceItem(
        evidence_type="tax_payments",
        source="qbo",
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
