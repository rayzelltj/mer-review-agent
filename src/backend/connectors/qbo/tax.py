from __future__ import annotations

from typing import Any

from .client import QBOHttpError, qbo_get
from .config import QBOConfig


def _extract_items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("QueryResponse"), dict):
        items = payload["QueryResponse"].get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        if isinstance(items, dict):
            return [items]
    items = payload.get(key)
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if isinstance(items, dict):
        return [items]
    return []


def _fetch_tax_query_payload(config: QBOConfig, entity: str) -> dict[str, Any]:
    return qbo_get(
        config,
        f"/v3/company/{config.realm_id}/query",
        params={"query": f"select * from {entity}"},
    )


def fetch_tax_agencies(config: QBOConfig) -> list[dict[str, Any]]:
    """Fetch QBO TaxAgency list."""
    return tax_agencies_from_payload(fetch_tax_agencies_payload(config))


def tax_agencies_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_items(payload, "TaxAgency")


def fetch_tax_agencies_payload(config: QBOConfig) -> dict[str, Any]:
    try:
        return qbo_get(
            config,
            f"/v3/company/{config.realm_id}/taxagency",
        )
    except QBOHttpError as exc:
        if exc.status in (400, 405):
            return _fetch_tax_query_payload(config, "TaxAgency")
        raise


def fetch_tax_returns(
    config: QBOConfig,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch QBO TaxReturn list."""
    return tax_returns_from_payload(
        fetch_tax_returns_payload(config, start_date=start_date, end_date=end_date)
    )


def tax_returns_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_items(payload, "TaxReturn")


def fetch_tax_returns_payload(
    config: QBOConfig,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        return qbo_get(
            config,
            f"/v3/company/{config.realm_id}/taxreturn",
            params=params or None,
        )
    except QBOHttpError as exc:
        if exc.status in (400, 405):
            return _fetch_tax_query_payload(config, "TaxReturn")
        raise


def fetch_tax_payments(
    config: QBOConfig,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch QBO TaxPayment list."""
    return tax_payments_from_payload(
        fetch_tax_payments_payload(config, start_date=start_date, end_date=end_date)
    )


def tax_payments_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_items(payload, "TaxPayment")


def fetch_tax_payments_payload(
    config: QBOConfig,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        return qbo_get(
            config,
            f"/v3/company/{config.realm_id}/taxpayment",
            params=params or None,
        )
    except QBOHttpError as exc:
        if exc.status in (400, 405):
            return _fetch_tax_query_payload(config, "TaxPayment")
        raise
