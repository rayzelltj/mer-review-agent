from __future__ import annotations

from typing import Any

from .client import qbo_get
from .config import QBOConfig


def _fetch_aging_report(
    config: QBOConfig,
    *,
    report_name: str,
    as_of_date: str,
    aging_method: str,
) -> dict[str, Any]:
    return qbo_get(
        config,
        f"/v3/company/{config.realm_id}/reports/{report_name}",
        params={
            "report_date": as_of_date,
            "aging_method": aging_method,
        },
    )


def fetch_aged_payables_summary(
    config: QBOConfig,
    *,
    as_of_date: str,
    aging_method: str = "Report_Date",
) -> dict[str, Any]:
    """Fetch QBO Aged Payables Summary report JSON."""
    return _fetch_aging_report(
        config,
        report_name="AgedPayables",
        as_of_date=as_of_date,
        aging_method=aging_method,
    )


def fetch_aged_payables_detail(
    config: QBOConfig,
    *,
    as_of_date: str,
    aging_method: str = "Report_Date",
) -> dict[str, Any]:
    """Fetch QBO Aged Payables Detail report JSON."""
    return _fetch_aging_report(
        config,
        report_name="AgedPayables",
        as_of_date=as_of_date,
        aging_method=aging_method,
    )


def fetch_aged_receivables_summary(
    config: QBOConfig,
    *,
    as_of_date: str,
    aging_method: str = "Report_Date",
) -> dict[str, Any]:
    """Fetch QBO Aged Receivables Summary report JSON."""
    return _fetch_aging_report(
        config,
        report_name="AgedReceivables",
        as_of_date=as_of_date,
        aging_method=aging_method,
    )


def fetch_aged_receivables_detail(
    config: QBOConfig,
    *,
    as_of_date: str,
    aging_method: str = "Report_Date",
) -> dict[str, Any]:
    """Fetch QBO Aged Receivables Detail report JSON."""
    return _fetch_aging_report(
        config,
        report_name="AgedReceivables",
        as_of_date=as_of_date,
        aging_method=aging_method,
    )
