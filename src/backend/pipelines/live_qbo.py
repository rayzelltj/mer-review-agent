from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from adapters.qbo.intercompany import intercompany_balance_sheets_to_evidence
from adapters.qbo.pipeline import build_qbo_aging_evidence, build_qbo_snapshots, build_qbo_tax_evidence
from adapters.qbo.balance_sheet import balance_sheet_snapshot_from_report
from common.rules_engine.models import EvidenceBundle, EvidenceItem
from connectors.qbo.accounts import fetch_accounts_all
from connectors.qbo.aging import (
    fetch_aged_payables_detail,
    fetch_aged_payables_summary,
    fetch_aged_receivables_detail,
    fetch_aged_receivables_summary,
)
from connectors.qbo.config import QBOConfig, get_qbo_config
from connectors.qbo.intercompany import fetch_counterparty_balance_sheets
from connectors.qbo.reports import fetch_balance_sheet, fetch_profit_and_loss
from connectors.qbo.tax import (
    fetch_tax_agencies_payload,
    fetch_tax_payments_payload,
    fetch_tax_returns_payload,
    tax_agencies_from_payload,
    tax_payments_from_payload,
    tax_returns_from_payload,
)

from .data_source import ReviewInputs
from .snapshots import (
    BlobSnapshotStore,
    MultiSnapshotStore,
    SnapshotStore,
    default_local_snapshot_store,
)


@dataclass(frozen=True)
class CounterpartyConfig:
    name: str
    realm_id: str


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    realm_id: str
    counterparties: tuple[CounterpartyConfig, ...] = ()


INTERCOMPANY_NAME_PATTERNS = (
    "intercompany",
    "inter-company",
    "due to",
    "due from",
    "loan from",
    "loan to",
    "shareholder loan",
)


class LiveQBODataSource:
    def __init__(
        self,
        *,
        snapshot_store: SnapshotStore | None = None,
        client_config_path: Path | None = None,
    ) -> None:
        self._client_config_path = client_config_path or _default_client_config_path()
        self._clients = _load_client_configs(self._client_config_path)
        self._snapshot_store = snapshot_store or _default_snapshot_store()

    def build_review_inputs(self, *, client_id: str, period_end: date) -> ReviewInputs:
        client = self._clients.get(client_id)
        if client is None:
            raise ValueError(f"Unknown client_id '{client_id}' in {self._client_config_path}.")

        primary_config = _config_for_realm(client.realm_id)

        balance_sheet_report = fetch_balance_sheet(
            primary_config,
            end_date=period_end.isoformat(),
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_balance_sheet",
            payload=balance_sheet_report,
        )
        _validate_report_payload(
            balance_sheet_report,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/reports/BalanceSheet",
                {
                    "end_date": period_end.isoformat(),
                    "accounting_method": "Accrual",
                },
            ),
            snapshot_name="qbo_balance_sheet",
            client_id=client_id,
            period_end=period_end,
            header_keys=("EndPeriod",),
        )

        pnl_start = _first_day_months_ago(period_end, 4)
        profit_and_loss_report = fetch_profit_and_loss(
            primary_config,
            start_date=pnl_start.isoformat(),
            end_date=period_end.isoformat(),
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_profit_and_loss",
            payload=profit_and_loss_report,
        )
        _validate_report_payload(
            profit_and_loss_report,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/reports/ProfitAndLoss",
                {
                    "start_date": pnl_start.isoformat(),
                    "end_date": period_end.isoformat(),
                    "accounting_method": "Accrual",
                },
            ),
            snapshot_name="qbo_profit_and_loss",
            client_id=client_id,
            period_end=period_end,
            header_keys=("StartPeriod", "EndPeriod"),
        )

        accounts_payload = fetch_accounts_all(primary_config)
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_accounts",
            payload=accounts_payload,
        )
        _validate_accounts_payload(
            accounts_payload,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/query",
                {
                    "query": "select * from Account startposition 1 maxresults 1000",
                },
            ),
            snapshot_name="qbo_accounts",
            client_id=client_id,
            period_end=period_end,
        )

        ap_summary = fetch_aged_payables_summary(primary_config, as_of_date=period_end.isoformat())
        ap_detail = fetch_aged_payables_detail(primary_config, as_of_date=period_end.isoformat())
        ar_summary = fetch_aged_receivables_summary(primary_config, as_of_date=period_end.isoformat())
        ar_detail = fetch_aged_receivables_detail(primary_config, as_of_date=period_end.isoformat())

        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_aged_payables_summary",
            payload=ap_summary,
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_aged_payables_detail",
            payload=ap_detail,
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_aged_receivables_summary",
            payload=ar_summary,
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_aged_receivables_detail",
            payload=ar_detail,
        )
        _validate_report_payload(
            ap_summary,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/reports/AgedPayables",
                {"report_date": period_end.isoformat(), "aging_method": "Report_Date"},
            ),
            snapshot_name="qbo_aged_payables_summary",
            client_id=client_id,
            period_end=period_end,
            header_keys=("EndPeriod",),
        )
        _validate_report_payload(
            ap_detail,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/reports/AgedPayables",
                {"report_date": period_end.isoformat(), "aging_method": "Report_Date"},
            ),
            snapshot_name="qbo_aged_payables_detail",
            client_id=client_id,
            period_end=period_end,
            header_keys=("EndPeriod",),
        )
        _validate_report_payload(
            ar_summary,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/reports/AgedReceivables",
                {"report_date": period_end.isoformat(), "aging_method": "Report_Date"},
            ),
            snapshot_name="qbo_aged_receivables_summary",
            client_id=client_id,
            period_end=period_end,
            header_keys=("EndPeriod",),
        )
        _validate_report_payload(
            ar_detail,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/reports/AgedReceivables",
                {"report_date": period_end.isoformat(), "aging_method": "Report_Date"},
            ),
            snapshot_name="qbo_aged_receivables_detail",
            client_id=client_id,
            period_end=period_end,
            header_keys=("EndPeriod",),
        )

        tax_agencies_payload = fetch_tax_agencies_payload(primary_config)
        tax_returns_payload = fetch_tax_returns_payload(primary_config)
        tax_payments_payload = fetch_tax_payments_payload(primary_config)

        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_tax_agencies",
            payload=tax_agencies_payload,
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_tax_returns",
            payload=tax_returns_payload,
        )
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name="qbo_tax_payments",
            payload=tax_payments_payload,
        )
        _validate_tax_payload(
            tax_agencies_payload,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/taxagency",
            ),
            snapshot_name="qbo_tax_agencies",
            client_id=client_id,
            period_end=period_end,
            item_key="TaxAgency",
        )
        _validate_tax_payload(
            tax_returns_payload,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/taxreturn",
            ),
            snapshot_name="qbo_tax_returns",
            client_id=client_id,
            period_end=period_end,
            item_key="TaxReturn",
        )
        _validate_tax_payload(
            tax_payments_payload,
            endpoint=_format_endpoint(
                primary_config.base_url,
                f"/v3/company/{primary_config.realm_id}/taxpayment",
            ),
            snapshot_name="qbo_tax_payments",
            client_id=client_id,
            period_end=period_end,
            item_key="TaxPayment",
        )

        tax_agencies = tax_agencies_from_payload(tax_agencies_payload)
        tax_returns = tax_returns_from_payload(tax_returns_payload)
        tax_payments = tax_payments_from_payload(tax_payments_payload)

        counterparty_payloads: list[dict[str, Any]] = []
        if client.counterparties:
            counterparty_configs = [
                _config_for_realm(cp.realm_id) for cp in client.counterparties
            ]
            counterparty_payloads = fetch_counterparty_balance_sheets(
                counterparty_configs=counterparty_configs,
                end_date=period_end.isoformat(),
            )
            for cp, payload in zip(client.counterparties, counterparty_payloads):
                safe_name = _safe_slug(cp.name or cp.realm_id)
                snapshot_name = f"qbo_balance_sheet_counterparty_{safe_name}"
                self._snapshot_store.save_json(
                    client_id=client_id,
                    period_end=period_end,
                    name=snapshot_name,
                    payload=payload,
                )
                _validate_report_payload(
                    payload,
                    endpoint=_format_endpoint(
                        primary_config.base_url,
                        f"/v3/company/{cp.realm_id}/reports/BalanceSheet",
                        {
                            "end_date": period_end.isoformat(),
                            "accounting_method": "Accrual",
                        },
                    ),
                    snapshot_name=snapshot_name,
                    client_id=client_id,
                    period_end=period_end,
                    header_keys=("EndPeriod",),
                )

        snapshots = build_qbo_snapshots(
            balance_sheet_report=balance_sheet_report,
            profit_and_loss_report=profit_and_loss_report,
            accounts_payload=accounts_payload,
            realm_id=primary_config.realm_id,
            pnl_summarize_by_month=False,
        )

        aging_bundle = build_qbo_aging_evidence(
            ap_summary_report=ap_summary,
            ap_detail_report=ap_detail,
            ar_summary_report=ar_summary,
            ar_detail_report=ar_detail,
        )
        tax_bundle = build_qbo_tax_evidence(
            tax_agencies_payload=tax_agencies,
            tax_returns_payload=tax_returns,
            tax_payments_payload=tax_payments,
        )

        items: list[EvidenceItem] = []
        items += aging_bundle.items
        items += tax_bundle.items

        intercompany_payload = _build_intercompany_payload(
            counterparty_payloads,
            client,
            period_end,
        )
        if intercompany_payload is not None:
            items.append(
                intercompany_balance_sheets_to_evidence(
                    intercompany_payload, as_of_date=period_end
                )
            )

        return ReviewInputs(
            period_end=period_end,
            balance_sheet=snapshots.balance_sheet,
            prior_balance_sheets=(),
            profit_and_loss=snapshots.profit_and_loss,
            evidence=EvidenceBundle(items=items),
            reconciliations=tuple(),
        )

    def save_snapshot(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        self._snapshot_store.save_json(
            client_id=client_id,
            period_end=period_end,
            name=name,
            payload=payload,
        )


def _default_snapshot_store() -> SnapshotStore:
    stores: list[SnapshotStore] = [default_local_snapshot_store()]
    enabled = os.getenv("BLOB_SNAPSHOT_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    if enabled:
        stores.append(BlobSnapshotStore())
    return MultiSnapshotStore(stores=tuple(stores))


def _default_client_config_path() -> Path:
    override = os.getenv("CLIENT_CONFIG_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "config" / "clients.json"


def _load_client_configs(path: Path) -> dict[str, ClientConfig]:
    if not path.exists():
        raise FileNotFoundError(f"Client config file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "clients" not in raw:
        raise ValueError("Client config must contain top-level 'clients' object.")

    clients: dict[str, ClientConfig] = {}
    for client_id, entry in (raw.get("clients") or {}).items():
        if not isinstance(entry, dict):
            continue
        realm_id = str(entry.get("realm_id") or "").strip()
        if not realm_id:
            continue
        counterparties = []
        for cp in entry.get("counterparties", []) or []:
            if not isinstance(cp, dict):
                continue
            cp_name = str(cp.get("name") or "").strip()
            cp_realm = str(cp.get("realm_id") or "").strip()
            if not cp_realm:
                continue
            counterparties.append(CounterpartyConfig(name=cp_name, realm_id=cp_realm))
        clients[str(client_id)] = ClientConfig(
            client_id=str(client_id),
            realm_id=realm_id,
            counterparties=tuple(counterparties),
        )
    return clients


def _config_for_realm(realm_id: str) -> QBOConfig:
    base = get_qbo_config()
    return QBOConfig(
        env=base.env,
        base_url=base.base_url,
        client_id=base.client_id,
        client_secret=base.client_secret,
        realm_id=realm_id,
        access_token=base.access_token,
        refresh_token=base.refresh_token,
        token_expires_at=base.token_expires_at,
    )


def _first_day_months_ago(period_end: date, months_back: int) -> date:
    if months_back < 0:
        raise ValueError("months_back must be >= 0")
    year = period_end.year
    month = period_end.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _build_intercompany_payload(
    payloads: list[dict[str, Any]],
    client: ClientConfig,
    period_end: date,
) -> dict[str, Any] | None:
    if not payloads or not client.counterparties:
        return None

    items: list[dict[str, Any]] = []
    for payload, counterparty in zip(payloads, client.counterparties):
        snapshot = balance_sheet_snapshot_from_report(
            payload,
            include_rows_without_id=False,
            include_summary_totals=False,
        )
        for acct in snapshot.accounts:
            if not _matches_intercompany(acct.name):
                continue
            items.append(
                {
                    "company": counterparty.name or counterparty.realm_id,
                    "counterparty": client.client_id,
                    "balance": str(acct.balance),
                    "account_name": acct.name,
                    "account_ref": acct.account_ref,
                }
            )

    return {"as_of_date": period_end.isoformat(), "items": items}


def _matches_intercompany(name: str) -> bool:
    lowered = (name or "").lower()
    return any(token in lowered for token in INTERCOMPANY_NAME_PATTERNS)


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return cleaned or "unknown"


def _format_endpoint(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    endpoint = f"{base_url}{path}"
    if params:
        endpoint = f"{endpoint}?{urlencode(params)}"
    return endpoint


def _snapshot_path(client_id: str, period_end: date, name: str) -> Path:
    root = default_local_snapshot_store().root_dir
    return root / client_id / period_end.isoformat() / f"{name}.json"


def _raise_payload_error(
    *,
    endpoint: str,
    snapshot_name: str,
    client_id: str,
    period_end: date,
    missing: list[str],
) -> None:
    snapshot_path = _snapshot_path(client_id, period_end, snapshot_name)
    missing_str = ", ".join(missing)
    raise ValueError(
        f"Invalid QBO response from {endpoint} (snapshot {snapshot_path}) missing keys: {missing_str}"
    )


def _validate_report_payload(
    payload: dict[str, Any],
    *,
    endpoint: str,
    snapshot_name: str,
    client_id: str,
    period_end: date,
    header_keys: tuple[str, ...],
) -> None:
    missing: list[str] = []
    if not isinstance(payload, dict):
        missing.append("<payload>")
    else:
        header = payload.get("Header")
        if not isinstance(header, dict):
            missing.append("Header")
        else:
            for key in header_keys:
                value = header.get(key)
                if value in (None, ""):
                    missing.append(f"Header.{key}")
        rows = payload.get("Rows")
        if not isinstance(rows, dict):
            missing.append("Rows")

    if missing:
        _raise_payload_error(
            endpoint=endpoint,
            snapshot_name=snapshot_name,
            client_id=client_id,
            period_end=period_end,
            missing=missing,
        )


def _validate_accounts_payload(
    payload: dict[str, Any],
    *,
    endpoint: str,
    snapshot_name: str,
    client_id: str,
    period_end: date,
) -> None:
    missing: list[str] = []
    if not isinstance(payload, dict):
        missing.append("<payload>")
    else:
        query_response = payload.get("QueryResponse")
        if not isinstance(query_response, dict):
            missing.append("QueryResponse")
        elif "Account" not in query_response:
            missing.append("QueryResponse.Account")

    if missing:
        _raise_payload_error(
            endpoint=endpoint,
            snapshot_name=snapshot_name,
            client_id=client_id,
            period_end=period_end,
            missing=missing,
        )


def _validate_tax_payload(
    payload: dict[str, Any],
    *,
    endpoint: str,
    snapshot_name: str,
    client_id: str,
    period_end: date,
    item_key: str,
) -> None:
    missing: list[str] = []
    if not isinstance(payload, dict):
        missing.append("<payload>")
    else:
        if item_key not in payload:
            query_response = payload.get("QueryResponse")
            if not (isinstance(query_response, dict) and item_key in query_response):
                missing.append(item_key)

    if missing:
        _raise_payload_error(
            endpoint=endpoint,
            snapshot_name=snapshot_name,
            client_id=client_id,
            period_end=period_end,
            missing=missing,
        )
