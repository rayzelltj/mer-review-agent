from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.rules_engine.models import BalanceSheetSnapshot, ProfitAndLossSnapshot

from .accounts import QBOAccountTypeInfo, account_type_map_from_accounts_payload
from .balance_sheet import balance_sheet_snapshot_from_report
from .profit_and_loss import profit_and_loss_snapshot_from_report


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
    )
    pnl = (
        profit_and_loss_snapshot_from_report(profit_and_loss_report)
        if profit_and_loss_report is not None
        else None
    )
    return QBOAdapterOutputs(
        balance_sheet=bs,
        profit_and_loss=pnl,
        account_type_map=account_type_map,
    )

