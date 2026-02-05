from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.rules_engine.models import BalanceSheetSnapshot, EvidenceBundle, ProfitAndLossSnapshot

from .accounts import QBOAccountTypeInfo, account_type_map_from_accounts_payload
from .aging_reports import aging_report_to_evidence
from .balance_sheet import balance_sheet_snapshot_from_report
from .profit_and_loss import profit_and_loss_snapshot_from_report
from .tax import tax_agencies_to_evidence, tax_payments_to_evidence, tax_returns_to_evidence


@dataclass(frozen=True)
class QBOAdapterOutputs:
    balance_sheet: BalanceSheetSnapshot
    profit_and_loss: ProfitAndLossSnapshot | None
    account_type_map: dict[str, QBOAccountTypeInfo]


def build_qbo_snapshots(
    *,
    balance_sheet_report: dict[str, Any],
    profit_and_loss_report: dict[str, Any] | None = None,
    accounts_payload: dict[str, Any] | None = None,
    realm_id: str | None = None,
    include_rows_without_id: bool = False,
    include_summary_totals: bool = False,
    pnl_summarize_by_month: bool = False,
) -> QBOAdapterOutputs:
    """
    Convenience helper that assembles canonical snapshots from raw QBO payloads.

    This is an adapter-layer helper (no network calls). It:
    - builds an AccountType/SubType map from the Accounts payload (if provided)
    - parses the Balance Sheet report into a BalanceSheetSnapshot (with type/subtype enrichment)
    - optionally parses the Profit & Loss report into a ProfitAndLossSnapshot
    """
    account_type_map = (
        account_type_map_from_accounts_payload(accounts_payload) if accounts_payload else {}
    )
    bs = balance_sheet_snapshot_from_report(
        balance_sheet_report,
        realm_id=realm_id,
        account_types=account_type_map,
        include_rows_without_id=include_rows_without_id,
        include_summary_totals=include_summary_totals,
    )
    pnl = (
        profit_and_loss_snapshot_from_report(
            profit_and_loss_report, summarize_by_month=pnl_summarize_by_month
        )
        if profit_and_loss_report is not None
        else None
    )
    return QBOAdapterOutputs(
        balance_sheet=bs,
        profit_and_loss=pnl,
        account_type_map=account_type_map,
    )


def build_qbo_aging_evidence(
    *,
    ap_summary_report: dict[str, Any] | None = None,
    ap_detail_report: dict[str, Any] | None = None,
    ar_summary_report: dict[str, Any] | None = None,
    ar_detail_report: dict[str, Any] | None = None,
) -> EvidenceBundle:
    """
    Convert QBO AP/AR aging reports into EvidenceItems for subledger reconciliation and aging rules.
    """
    items = []
    if ap_summary_report is not None:
        items += aging_report_to_evidence(ap_summary_report, report_type="ap", report_kind="summary")
    if ap_detail_report is not None:
        items += aging_report_to_evidence(ap_detail_report, report_type="ap", report_kind="detail")
    if ar_summary_report is not None:
        items += aging_report_to_evidence(ar_summary_report, report_type="ar", report_kind="summary")
    if ar_detail_report is not None:
        items += aging_report_to_evidence(ar_detail_report, report_type="ar", report_kind="detail")
    return EvidenceBundle(items=items)


def build_qbo_tax_evidence(
    *,
    tax_agencies_payload: list[dict[str, Any]] | None = None,
    tax_returns_payload: list[dict[str, Any]] | None = None,
    tax_payments_payload: list[dict[str, Any]] | None = None,
) -> EvidenceBundle:
    """
    Convert QBO TaxAgency/TaxReturn/TaxPayment payloads into EvidenceItems for tax rules.
    """
    items = []
    if tax_agencies_payload is not None:
        items.append(tax_agencies_to_evidence(tax_agencies_payload))
    if tax_returns_payload is not None:
        items.append(tax_returns_to_evidence(tax_returns_payload))
    if tax_payments_payload is not None:
        items.append(tax_payments_to_evidence(tax_payments_payload))
    return EvidenceBundle(items=items)
