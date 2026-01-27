from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .config import ClientRulesConfig, VarianceThreshold
from .models import (
    BalanceSheetSnapshot,
    EvidenceBundle,
    ProfitAndLossSnapshot,
    ReconciliationSnapshot,
)


@dataclass(frozen=True)
class RuleContext:
    period_end: date
    balance_sheet: BalanceSheetSnapshot
    profit_and_loss: Optional[ProfitAndLossSnapshot] = None
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    reconciliations: tuple[ReconciliationSnapshot, ...] = ()
    client_config: ClientRulesConfig = field(default_factory=ClientRulesConfig)

    def get_account_balance(self, account_ref: str) -> Optional[Decimal]:
        for acct in self.balance_sheet.accounts:
            if acct.account_ref == account_ref:
                return acct.balance
        return None

    def get_revenue_total(self) -> Optional[Decimal]:
        if not self.profit_and_loss:
            return None
        return self.profit_and_loss.get_total("revenue")


def compute_allowed_variance(
    *,
    threshold: VarianceThreshold,
    revenue_total: Optional[Decimal],
) -> Decimal:
    floor_amount = threshold.floor_amount or Decimal("0")
    pct = threshold.pct_of_revenue or Decimal("0")
    revenue_component = Decimal("0")
    if revenue_total is not None:
        revenue_component = (abs(revenue_total) * pct).copy_abs()
    return max(floor_amount, revenue_component)


def quantize_amount(value: Decimal, quantize: Optional[Decimal]) -> Decimal:
    if quantize is None:
        return value
    return value.quantize(quantize, rounding=ROUND_HALF_UP)
