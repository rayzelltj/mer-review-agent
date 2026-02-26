from __future__ import annotations

import calendar
import concurrent.futures
import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from adapters.qbo.intercompany import intercompany_balance_sheets_to_evidence
from adapters.qbo.pipeline import build_qbo_aging_evidence, build_qbo_snapshots, build_qbo_tax_evidence
from adapters.qbo.balance_sheet import balance_sheet_snapshot_from_report
from adapters.qbo.bank_cc_reconciliation import (
    active_bank_cc_accounts_from_accounts_payload,
    transaction_list_unreconciled_sums_from_report,
    trial_balance_register_balances_from_report,
)
from adapters.qbo.fixed_assets import (
    active_fixed_asset_accounts_from_accounts_payload,
    fixed_asset_ledger_transactions_from_report,
)
from adapters.mock_evidence.evidence_manifest import evidence_bundle_from_manifest
from adapters.qbo.profit_and_loss import expense_month_over_month_from_report
from common.rules_engine.models import EvidenceBundle, EvidenceItem
from connectors.drive.client import download_file_bytes
from connectors.drive.config import build_drive_config, is_drive_evidence_enabled
from connectors.qbo.accounts import fetch_accounts_all
from connectors.qbo.aging import (
    fetch_aged_payables_detail,
    fetch_aged_payables_summary,
    fetch_aged_receivables_detail,
    fetch_aged_receivables_summary,
)
from connectors.qbo.client_store import get_qbo_client_record
from connectors.qbo.config import QBOConfig, build_qbo_config, get_client_store_mode
from connectors.qbo.intercompany import fetch_counterparty_balance_sheets
from connectors.qbo.reports import (
    fetch_balance_sheet,
    fetch_profit_and_loss,
    fetch_transaction_list_by_account,
    fetch_trial_balance,
)
from connectors.qbo.tax import (
    fetch_tax_agencies_payload,
    fetch_tax_payments_payload,
    fetch_tax_returns_payload,
    tax_agencies_from_payload,
    tax_payments_from_payload,
    tax_returns_from_payload,
)
from common.telemetry import traced_phase

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
    refresh_token: str | None = None


INTERCOMPANY_NAME_PATTERNS = (
    "intercompany",
    "inter-company",
    "due to",
    "due from",
    "loan from",
    "loan to",
    "shareholder loan",
)
LOGGER = logging.getLogger(__name__)
_QBO_FETCH_CONCURRENCY = int(os.getenv("QBO_FETCH_CONCURRENCY", "5"))


class LiveQBODataSource:
    def __init__(
        self,
        *,
        snapshot_store: SnapshotStore | None = None,
        client_config_path: Path | None = None,
        client_store_mode: str | None = None,
        user_principal_id: str | None = None,
    ) -> None:
        self._client_store_mode = (client_store_mode or get_client_store_mode()).strip().lower()
        self._user_principal_id = str(user_principal_id or "").strip() or None
        if self._client_store_mode == "file":
            self._client_config_path = client_config_path or _default_client_config_path()
            self._clients = _load_client_configs(self._client_config_path)
        else:
            self._client_config_path = client_config_path
            self._clients = {}
        self._snapshot_store = snapshot_store or _default_snapshot_store()

    def fetch_raw_data(self, *, client_id: str, period_end: date | str) -> dict[str, Any]:
        """Phase 1: Fetch all raw QBO API payloads and save them as snapshots.

        [PARALLELIZED] Uses a ThreadPoolExecutor to run independent QBO API calls
        concurrently (up to _QBO_FETCH_CONCURRENCY at a time).  The interface and
        returned dict are identical to the sequential version.
        """
        period_end = _coerce_period_end(period_end, context="fetch_raw_data")
        client = self._get_client_config(client_id)
        if client is None:
            if self._client_store_mode == "cosmos":
                raise ValueError(f"Unknown client_id '{client_id}' in Cosmos store.")
            raise ValueError(f"Unknown client_id '{client_id}' in {self._client_config_path}.")

        primary_config = _config_for_realm(
            client.realm_id,
            refresh_token=client.refresh_token,
            client_record_id=client.client_id,
            user_principal_id=self._user_principal_id,
        )

        raw: dict[str, Any] = {
            "client_id": client_id,
            "realm_id": primary_config.realm_id,
            "period_end": period_end.isoformat(),
        }

        # Compute derived dates before entering the traced phase.
        pnl_start = _first_day_months_ago(period_end, 4)
        pnl_monthly_start = _first_day_months_ago(period_end, 1)
        trial_balance_start = date(period_end.year, period_end.month, 1)
        tx_list_start = date(period_end.year, period_end.month, 1).isoformat()
        prior_period_ends = [_month_end_months_ago(period_end, m) for m in range(1, 4)]

        # Drive manifest is fast and needed for tx list date ranges — fetch before Round 1.
        manifest_payload, drive_items = _load_drive_manifest_evidence(
            client_id=client_id,
            period_end=period_end,
            user_principal_id=self._user_principal_id,
        )
        statement_end_by_ref, statement_end_by_id = _statement_end_dates_by_account(drive_items)

        with traced_phase(
            "balance_sheet.connector",
            logger=LOGGER,
            attributes={"client.id": client_id, "qbo.realm_id": primary_config.realm_id},
        ):
            # ── Round 1: submit all independent QBO fetches concurrently ─────────
            with concurrent.futures.ThreadPoolExecutor(max_workers=_QBO_FETCH_CONCURRENCY) as _pool:
                _f_bs = _pool.submit(
                    fetch_balance_sheet, primary_config, end_date=period_end.isoformat()
                )
                _f_prior = [
                    _pool.submit(
                        fetch_balance_sheet, primary_config, end_date=ppe.isoformat()
                    )
                    for ppe in prior_period_ends
                ]
                _f_pnl = _pool.submit(
                    fetch_profit_and_loss,
                    primary_config,
                    start_date=pnl_start.isoformat(),
                    end_date=period_end.isoformat(),
                )
                _f_pnl_monthly = _pool.submit(
                    fetch_profit_and_loss,
                    primary_config,
                    start_date=pnl_monthly_start.isoformat(),
                    end_date=period_end.isoformat(),
                    summarize_column_by="Month",
                )
                _f_tb = _pool.submit(
                    fetch_trial_balance,
                    primary_config,
                    start_date=trial_balance_start.isoformat(),
                    end_date=period_end.isoformat(),
                )
                _f_accounts = _pool.submit(fetch_accounts_all, primary_config)
                _f_ap_s = _pool.submit(
                    fetch_aged_payables_summary, primary_config, as_of_date=period_end.isoformat()
                )
                _f_ap_d = _pool.submit(
                    fetch_aged_payables_detail, primary_config, as_of_date=period_end.isoformat()
                )
                _f_ar_s = _pool.submit(
                    fetch_aged_receivables_summary, primary_config, as_of_date=period_end.isoformat()
                )
                _f_ar_d = _pool.submit(
                    fetch_aged_receivables_detail, primary_config, as_of_date=period_end.isoformat()
                )
                _f_tax_agencies = _pool.submit(fetch_tax_agencies_payload, primary_config)
                _f_tax_returns = _pool.submit(fetch_tax_returns_payload, primary_config)
                _f_tax_payments = _pool.submit(fetch_tax_payments_payload, primary_config)
            # All Round-1 futures are resolved when the `with` block exits.

            # ── Collect + validate + save: current balance sheet ─────────────────
            balance_sheet_report = _f_bs.result()
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
            raw["qbo_balance_sheet"] = balance_sheet_report

            # ── Collect + validate + save: prior balance sheets ──────────────────
            prior_balance_sheets_raw: list[dict[str, Any]] = []
            for months_back, (prior_period_end, _f) in enumerate(
                zip(prior_period_ends, _f_prior), start=1
            ):
                prior_report = _f.result()
                snapshot_name = f"qbo_balance_sheet_prior_{months_back}"
                self._snapshot_store.save_json(
                    client_id=client_id,
                    period_end=period_end,
                    name=snapshot_name,
                    payload=prior_report,
                )
                _validate_report_payload(
                    prior_report,
                    endpoint=_format_endpoint(
                        primary_config.base_url,
                        f"/v3/company/{primary_config.realm_id}/reports/BalanceSheet",
                        {
                            "end_date": prior_period_end.isoformat(),
                            "accounting_method": "Accrual",
                        },
                    ),
                    snapshot_name=snapshot_name,
                    client_id=client_id,
                    period_end=period_end,
                    header_keys=("EndPeriod",),
                )
                prior_balance_sheets_raw.append(
                    {
                        "period_end": prior_period_end.isoformat(),
                        "payload": prior_report,
                    }
                )
            raw["qbo_balance_sheets_prior"] = prior_balance_sheets_raw

            # ── Collect + validate + save: P&L ───────────────────────────────────
            profit_and_loss_report = _f_pnl.result()
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
            raw["qbo_profit_and_loss"] = profit_and_loss_report

            # ── Collect + validate + save: P&L monthly (optional) ────────────────
            profit_and_loss_monthly_report: dict[str, Any] | None = None
            try:
                profit_and_loss_monthly_report = _f_pnl_monthly.result()
                self._snapshot_store.save_json(
                    client_id=client_id,
                    period_end=period_end,
                    name="qbo_profit_and_loss_monthly",
                    payload=profit_and_loss_monthly_report,
                )
                _validate_report_payload(
                    profit_and_loss_monthly_report,
                    endpoint=_format_endpoint(
                        primary_config.base_url,
                        f"/v3/company/{primary_config.realm_id}/reports/ProfitAndLoss",
                        {
                            "start_date": pnl_monthly_start.isoformat(),
                            "end_date": period_end.isoformat(),
                            "accounting_method": "Accrual",
                            "summarize_column_by": "Month",
                        },
                    ),
                    snapshot_name="qbo_profit_and_loss_monthly",
                    client_id=client_id,
                    period_end=period_end,
                    header_keys=("StartPeriod", "EndPeriod"),
                )
            except Exception as exc:
                LOGGER.warning(
                    "Unable to fetch monthly ProfitAndLoss report for client_id=%s period_end=%s: %s",
                    client_id,
                    period_end,
                    exc,
                )
            raw["qbo_profit_and_loss_monthly"] = profit_and_loss_monthly_report

            # ── Collect + validate + save: trial balance ──────────────────────────
            trial_balance_report = _f_tb.result()
            self._snapshot_store.save_json(
                client_id=client_id,
                period_end=period_end,
                name="qbo_trial_balance",
                payload=trial_balance_report,
            )
            _validate_report_payload(
                trial_balance_report,
                endpoint=_format_endpoint(
                    primary_config.base_url,
                    f"/v3/company/{primary_config.realm_id}/reports/TrialBalance",
                    {
                        "start_date": trial_balance_start.isoformat(),
                        "end_date": period_end.isoformat(),
                        "accounting_method": "Accrual",
                    },
                ),
                snapshot_name="qbo_trial_balance",
                client_id=client_id,
                period_end=period_end,
                header_keys=("StartPeriod", "EndPeriod"),
            )
            raw["qbo_trial_balance"] = trial_balance_report

            # ── Collect + validate + save: accounts ───────────────────────────────
            accounts_payload = _f_accounts.result()
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
            raw["qbo_accounts"] = accounts_payload

            # ── Round 2: transaction lists (depend on accounts) ───────────────────
            bank_cc_scope = active_bank_cc_accounts_from_accounts_payload(
                accounts_payload,
                realm_id=primary_config.realm_id,
                active_only=True,
            )
            fixed_asset_scope = active_fixed_asset_accounts_from_accounts_payload(
                accounts_payload,
                realm_id=primary_config.realm_id,
                active_only=True,
            )

            def _fetch_bank_cc_tx(scoped_account: dict) -> dict[str, Any] | None:
                account_id = str(scoped_account.get("account_id") or "").strip()
                if not account_id:
                    return None
                account_ref = str(scoped_account.get("account_ref") or "").strip()
                statement_end_date = (
                    statement_end_by_ref.get(account_ref)
                    or statement_end_by_id.get(account_id)
                    or period_end
                )
                tx_payload = fetch_transaction_list_by_account(
                    primary_config,
                    account_id=account_id,
                    start_date=tx_list_start,
                    end_date=statement_end_date.isoformat(),
                    include_split_detail=True,
                )
                self._snapshot_store.save_json(
                    client_id=client_id,
                    period_end=period_end,
                    name=f"qbo_transaction_list_by_account_{account_id}",
                    payload=tx_payload,
                )
                return {
                    "account_id": account_id,
                    "account_ref": account_ref,
                    "account_name": scoped_account.get("account_name"),
                    "statement_end_date": (
                        statement_end_date.isoformat()
                        if isinstance(statement_end_date, date)
                        else str(statement_end_date)
                    ),
                    "payload": tx_payload,
                }

            def _fetch_fixed_asset_tx(scoped_account: dict) -> dict[str, Any] | None:
                account_id = str(scoped_account.get("account_id") or "").strip()
                if not account_id:
                    return None
                try:
                    tx_payload = fetch_transaction_list_by_account(
                        primary_config,
                        account_id=account_id,
                        start_date=tx_list_start,
                        end_date=period_end.isoformat(),
                        include_split_detail=True,
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to fetch fixed-asset transaction list for account_id=%s client_id=%s period_end=%s: %s",
                        account_id,
                        client_id,
                        period_end,
                        exc,
                    )
                    return None
                self._snapshot_store.save_json(
                    client_id=client_id,
                    period_end=period_end,
                    name=f"qbo_transaction_list_fixed_asset_{account_id}",
                    payload=tx_payload,
                )
                return {
                    "account_id": account_id,
                    "account_ref": str(scoped_account.get("account_ref") or "").strip(),
                    "account_name": scoped_account.get("account_name"),
                    "payload": tx_payload,
                }

            tx_list_payloads: list[dict[str, Any]] = []
            fixed_asset_tx_payloads: list[dict[str, Any]] = []
            bank_cc_list = list(bank_cc_scope)
            fixed_asset_list = list(fixed_asset_scope)

            if bank_cc_list or fixed_asset_list:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=_QBO_FETCH_CONCURRENCY
                ) as _pool:
                    _f_tx = [_pool.submit(_fetch_bank_cc_tx, a) for a in bank_cc_list]
                    _f_fa = [_pool.submit(_fetch_fixed_asset_tx, a) for a in fixed_asset_list]
                tx_list_payloads = [r for f in _f_tx if (r := f.result()) is not None]
                fixed_asset_tx_payloads = [r for f in _f_fa if (r := f.result()) is not None]

            # ── Collect + validate + save: AP/AR aging ────────────────────────────
            ap_summary = _f_ap_s.result()
            ap_detail = _f_ap_d.result()
            ar_summary = _f_ar_s.result()
            ar_detail = _f_ar_d.result()

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
            raw["qbo_aged_payables_summary"] = ap_summary
            raw["qbo_aged_payables_detail"] = ap_detail
            raw["qbo_aged_receivables_summary"] = ar_summary
            raw["qbo_aged_receivables_detail"] = ar_detail

            # ── Collect + validate + save: tax ────────────────────────────────────
            tax_agencies_payload = _f_tax_agencies.result()
            tax_returns_payload = _f_tax_returns.result()
            tax_payments_payload = _f_tax_payments.result()

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
            raw["qbo_tax_agencies"] = tax_agencies_payload
            raw["qbo_tax_returns"] = tax_returns_payload
            raw["qbo_tax_payments"] = tax_payments_payload

            # ── Counterparty balance sheets ────────────────────────────────────────
            counterparty_payloads: list[dict[str, Any]] = []
            if client.counterparties:
                counterparty_configs = [
                    _config_for_realm(
                        cp.realm_id,
                        refresh_token=client.refresh_token,
                        client_record_id=client.client_id,
                        user_principal_id=self._user_principal_id,
                    )
                    for cp in client.counterparties
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
            raw["counterparty_names"] = [cp.name for cp in client.counterparties]
            raw["counterparty_payloads"] = counterparty_payloads

            raw["tx_list_payloads"] = tx_list_payloads
            raw["fixed_asset_tx_payloads"] = fixed_asset_tx_payloads
            if manifest_payload is not None:
                raw["drive_evidence_manifest"] = manifest_payload
                raw["drive_evidence_items"] = [
                    item.model_dump(mode="json") for item in drive_items
                ]

        return raw

    def normalize_raw_data(self, *, raw: dict[str, Any]) -> ReviewInputs:
        """Phase 2: Normalize raw QBO payloads (from fetch_raw_data) into a ReviewInputs object.

        Accepts the dict returned by fetch_raw_data() (or deserialized from the raw_qbo_inputs artifact).
        Runs build_qbo_snapshots, build_qbo_aging_evidence, build_qbo_tax_evidence, and all
        evidence item construction.  Does NOT make any QBO API calls.
        """
        from connectors.qbo.client_store import get_qbo_client_record

        period_end = date.fromisoformat(raw["period_end"])
        realm_id = str(raw.get("realm_id") or "").strip()

        balance_sheet_report = raw["qbo_balance_sheet"]
        profit_and_loss_report = raw["qbo_profit_and_loss"]
        profit_and_loss_monthly_report: dict[str, Any] | None = raw.get("qbo_profit_and_loss_monthly")
        trial_balance_report = raw["qbo_trial_balance"]
        accounts_payload = raw["qbo_accounts"]
        ap_summary = raw["qbo_aged_payables_summary"]
        ap_detail = raw["qbo_aged_payables_detail"]
        ar_summary = raw["qbo_aged_receivables_summary"]
        ar_detail = raw["qbo_aged_receivables_detail"]
        tax_agencies_payload = raw["qbo_tax_agencies"]
        tax_returns_payload = raw["qbo_tax_returns"]
        tax_payments_payload = raw["qbo_tax_payments"]
        prior_balance_sheet_reports_raw: list[dict[str, Any]] = (
            raw.get("qbo_balance_sheets_prior") or []
        )
        prior_balance_sheet_reports: list[tuple[date, dict[str, Any]]] = []
        for entry in prior_balance_sheet_reports_raw:
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            period_end_raw = str(entry.get("period_end") or "").strip()
            if not period_end_raw:
                continue
            try:
                prior_period_end = date.fromisoformat(period_end_raw)
            except ValueError:
                LOGGER.warning(
                    "Ignoring invalid prior balance sheet period_end '%s' for realm_id=%s",
                    period_end_raw,
                    realm_id,
                )
                continue
            prior_balance_sheet_reports.append((prior_period_end, payload))

        # Re-hydrate tx_list_payloads — statement_end_date was serialized as ISO string
        tx_list_payloads_raw: list[dict[str, Any]] = raw.get("tx_list_payloads") or []
        tx_list_payloads: list[dict[str, Any]] = []
        for entry in tx_list_payloads_raw:
            rehydrated = dict(entry)
            sed = entry.get("statement_end_date")
            if isinstance(sed, str):
                try:
                    rehydrated["statement_end_date"] = date.fromisoformat(sed)
                except ValueError:
                    rehydrated["statement_end_date"] = period_end
            elif not isinstance(sed, date):
                rehydrated["statement_end_date"] = period_end
            tx_list_payloads.append(rehydrated)

        fixed_asset_tx_payloads: list[dict[str, Any]] = raw.get("fixed_asset_tx_payloads") or []

        manifest_payload: dict[str, Any] | None = raw.get("drive_evidence_manifest")
        drive_evidence_items_raw: list[dict[str, Any]] = raw.get("drive_evidence_items") or []
        drive_items: list[EvidenceItem] = []
        for item_dict in drive_evidence_items_raw:
            try:
                drive_items.append(EvidenceItem.model_validate(item_dict))
            except Exception as exc:
                LOGGER.warning("Failed to rehydrate drive evidence item: %s", exc)

        counterparty_payloads: list[dict[str, Any]] = raw.get("counterparty_payloads") or []
        counterparty_names: list[str | None] = raw.get("counterparty_names") or []

        with traced_phase(
            "balance_sheet.normalization",
            logger=LOGGER,
            attributes={"qbo.realm_id": realm_id},
        ):
            snapshots = build_qbo_snapshots(
                balance_sheet_report=balance_sheet_report,
                profit_and_loss_report=profit_and_loss_report,
                accounts_payload=accounts_payload,
                realm_id=realm_id,
                pnl_summarize_by_month=False,
            )
            prior_balance_sheets_list = []
            for prior_period_end, prior_report in sorted(
                prior_balance_sheet_reports,
                key=lambda item: item[0],
                reverse=True,
            ):
                try:
                    prior_snapshot = balance_sheet_snapshot_from_report(
                        prior_report,
                        realm_id=realm_id,
                        account_types=snapshots.account_type_map,
                        include_rows_without_id=True,
                        include_summary_totals=True,
                    )
                    prior_balance_sheets_list.append(prior_snapshot)
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to normalize prior balance sheet report period_end=%s realm_id=%s: %s",
                        prior_period_end,
                        realm_id,
                        exc,
                    )
            prior_balance_sheets = tuple(prior_balance_sheets_list)

            tax_agencies = tax_agencies_from_payload(tax_agencies_payload)
            tax_returns = tax_returns_from_payload(tax_returns_payload)
            tax_payments = tax_payments_from_payload(tax_payments_payload)

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

        coa_rows = active_bank_cc_accounts_from_accounts_payload(
            accounts_payload,
            realm_id=realm_id,
            active_only=True,
        )
        items.append(
            EvidenceItem(
                evidence_type="qbo_chart_of_accounts_bank_cc_active",
                source="qbo",
                as_of_date=period_end,
                meta={"accounts": coa_rows},
            )
        )

        trial_map = trial_balance_register_balances_from_report(
            trial_balance_report,
            realm_id=realm_id,
        )
        items.append(
            EvidenceItem(
                evidence_type="qbo_trial_balance_register_balance",
                source="qbo",
                as_of_date=period_end,
                meta={
                    "balances_by_account_ref": {ref: str(amount) for ref, amount in trial_map.items()},
                },
            )
        )

        if profit_and_loss_monthly_report is not None:
            try:
                expense_variance_meta = expense_month_over_month_from_report(
                    profit_and_loss_monthly_report,
                    current_period_end=period_end,
                )
                items.append(
                    EvidenceItem(
                        evidence_type="qbo_pnl_expense_monthly",
                        source="qbo",
                        as_of_date=period_end,
                        meta=expense_variance_meta,
                    )
                )
            except Exception as exc:
                LOGGER.warning(
                    "Unable to parse month-over-month expense lines period_end=%s: %s",
                    period_end,
                    exc,
                )

        for tx_payload in tx_list_payloads:
            account_id = str(tx_payload.get("account_id") or "").strip()
            account_ref = str(tx_payload.get("account_ref") or "").strip()
            report_payload = tx_payload.get("payload")
            summary = transaction_list_unreconciled_sums_from_report(
                {"payload": report_payload, "extra": {"account_id": account_id}},
                period_end=period_end,
                statement_end_date=tx_payload.get("statement_end_date") or period_end,
            )
            items.append(
                EvidenceItem(
                    evidence_type="qbo_transaction_list_unreconciled",
                    source="qbo",
                    as_of_date=period_end,
                    meta={
                        "account_id": account_id,
                        "account_ref": account_ref,
                        "account_name": tx_payload.get("account_name"),
                        "sum_not_reconciled_as_of_period_end": str(
                            summary["sum_not_reconciled_as_of_period_end"]
                        ),
                        "sum_not_reconciled_between_period_end_and_statement_end": str(
                            summary["sum_not_reconciled_between_period_end_and_statement_end"]
                        ),
                        "statement_end_date_used": (
                            tx_payload["statement_end_date"].isoformat()
                            if isinstance(tx_payload.get("statement_end_date"), date)
                            else None
                        ),
                        "clear_status_column_found": summary["clear_status_column_found"],
                        "parsed_rows": summary["parsed_rows"],
                        "ignored_rows": summary["ignored_rows"],
                    },
                )
            )

        fixed_asset_period_start = date(period_end.year, period_end.month, 1)
        for tx_payload in fixed_asset_tx_payloads:
            account_id = str(tx_payload.get("account_id") or "").strip()
            account_ref = str(tx_payload.get("account_ref") or "").strip()
            report_payload = tx_payload.get("payload")
            summary = fixed_asset_ledger_transactions_from_report(
                {"payload": report_payload, "extra": {"account_id": account_id}},
                period_start=fixed_asset_period_start,
                period_end=period_end,
            )
            items.append(
                EvidenceItem(
                    evidence_type="qbo_fixed_asset_ledger_transactions",
                    source="qbo",
                    as_of_date=period_end,
                    meta={
                        "account_id": account_id,
                        "account_ref": account_ref,
                        "account_name": tx_payload.get("account_name"),
                        "transactions": summary.get("transactions") or [],
                        "parsed_rows": summary.get("parsed_rows"),
                        "ignored_rows": summary.get("ignored_rows"),
                    },
                )
            )

        if manifest_payload is not None:
            items += drive_items

        # Reconstruct a minimal ClientConfig-like object for intercompany
        @dataclass(frozen=True)
        class _MinimalClient:
            client_id: str
            counterparties: tuple

        @dataclass(frozen=True)
        class _MinimalCP:
            name: str | None
            realm_id: str

        minimal_cps = tuple(
            _MinimalCP(name=name, realm_id="")
            for name in counterparty_names
        )
        minimal_client = _MinimalClient(
            client_id=str(raw.get("client_id") or ""),
            counterparties=minimal_cps,
        )
        intercompany_payload = _build_intercompany_payload(
            counterparty_payloads,
            minimal_client,  # type: ignore[arg-type]
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
            prior_balance_sheets=prior_balance_sheets,
            profit_and_loss=snapshots.profit_and_loss,
            evidence=EvidenceBundle(items=items),
            reconciliations=tuple(),
        )

    def build_review_inputs(self, *, client_id: str, period_end: date | str) -> ReviewInputs:
        """Backward-compatible monolith: fetch raw data then normalize in one call."""
        period_end = _coerce_period_end(period_end, context="build_review_inputs")
        raw = self.fetch_raw_data(client_id=client_id, period_end=period_end)
        return self.normalize_raw_data(raw=raw)

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

    def _get_client_config(self, client_id: str) -> ClientConfig | None:
        if self._client_store_mode == "file":
            return self._clients.get(client_id)

        record = get_qbo_client_record(
            client_id,
            user_principal_id=self._user_principal_id,
        )
        if record is None:
            return None

        realm_id = str(record.get("realm_id") or "").strip()
        refresh_token = str(record.get("refresh_token") or "").strip()
        if not realm_id or not refresh_token:
            raise ValueError(f"Client record for '{client_id}' missing realm_id or refresh_token.")

        counterparties = []
        for cp in record.get("counterparties", []) or []:
            if not isinstance(cp, dict):
                continue
            cp_name = str(cp.get("name") or "").strip()
            cp_realm = str(cp.get("realm_id") or "").strip()
            if not cp_realm:
                continue
            counterparties.append(CounterpartyConfig(name=cp_name, realm_id=cp_realm))

        return ClientConfig(
            client_id=str(client_id),
            realm_id=realm_id,
            counterparties=tuple(counterparties),
            refresh_token=refresh_token,
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


def _config_for_realm(
    realm_id: str,
    *,
    refresh_token: str | None = None,
    client_record_id: str | None = None,
    user_principal_id: str | None = None,
) -> QBOConfig:
    if refresh_token:
        return build_qbo_config(
            realm_id=realm_id,
            access_token="",
            refresh_token=refresh_token,
            token_expires_at="",
            client_record_id=client_record_id,
            user_principal_id=user_principal_id,
        )
    return build_qbo_config(
        realm_id=realm_id,
        client_record_id=client_record_id,
        user_principal_id=user_principal_id,
    )


def _coerce_period_end(period_end: date | str, *, context: str) -> date:
    if isinstance(period_end, date):
        return period_end
    raw_value = str(period_end or "").strip()
    if not raw_value:
        raise ValueError(f"{context}: period_end is required (YYYY-MM-DD).")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{context}: invalid period_end '{raw_value}' (expected YYYY-MM-DD)."
        ) from exc


def _first_day_months_ago(period_end: date, months_back: int) -> date:
    if months_back < 0:
        raise ValueError("months_back must be >= 0")
    year = period_end.year
    month = period_end.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _month_end_months_ago(period_end: date, months_back: int) -> date:
    if months_back < 0:
        raise ValueError("months_back must be >= 0")
    year = period_end.year
    month = period_end.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    day = calendar.monthrange(year, month)[1]
    return date(year, month, day)


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


def _statement_end_dates_by_account(items: list[EvidenceItem]) -> tuple[dict[str, date], dict[str, date]]:
    by_ref: dict[str, date] = {}
    by_id: dict[str, date] = {}

    def _remember(target: dict[str, date], key: str, value: date) -> None:
        if not key:
            return
        current = target.get(key)
        if current is None or value > current:
            target[key] = value

    for item in items:
        if item.evidence_type != "statement_balance_attachment":
            continue
        statement_end = item.statement_end_date or item.as_of_date
        if statement_end is None:
            continue
        meta = item.meta or {}
        account_ref = str(meta.get("account_ref") or "").strip()
        account_id = str(meta.get("account_id") or "").strip()
        if account_ref:
            _remember(by_ref, account_ref, statement_end)
            canonical_id = account_ref.split("::")[-1]
            if canonical_id and canonical_id != account_ref:
                _remember(by_id, canonical_id, statement_end)
        if account_id:
            _remember(by_id, account_id, statement_end)

    return by_ref, by_id


def _load_drive_manifest_evidence(
    *,
    client_id: str,
    period_end: date,
    user_principal_id: str | None,
) -> tuple[dict[str, Any] | None, list[EvidenceItem]]:
    if not is_drive_evidence_enabled():
        return None, []

    try:
        cfg = build_drive_config(
            client_id=client_id,
            user_principal_id=user_principal_id,
        )
    except Exception as exc:
        LOGGER.info("Drive evidence disabled for client %s: %s", client_id, exc)
        return None, []

    file_id = str(cfg.evidence_manifest_file_id or "").strip()
    if not file_id:
        return None, []

    try:
        with traced_phase(
            "balance_sheet.drive_evidence",
            logger=LOGGER,
            attributes={"client.id": client_id, "drive.file_id": file_id},
        ):
            raw = download_file_bytes(
                cfg,
                file_id=file_id,
                export_mime_type="application/json",
            )
            manifest = json.loads(raw.decode("utf-8"))
            bundle = evidence_bundle_from_manifest(manifest, source_default="google_drive")
    except Exception as exc:
        LOGGER.warning(
            "Drive evidence manifest load failed client_id=%s period_end=%s file_id=%s error=%s",
            client_id,
            period_end.isoformat(),
            file_id,
            exc,
        )
        return None, []

    if not isinstance(manifest, dict):
        LOGGER.warning("Drive evidence manifest file is not a JSON object: %s", file_id)
        return None, []

    return manifest, list(bundle.items)


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
