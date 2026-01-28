import os
import sys


# Ensure `src/backend` is on sys.path so imports like `import common...` work.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from datetime import date

import pytest

from common.rules_engine.config import ClientRulesConfig
from common.rules_engine.context import RuleContext
from common.rules_engine.models import (
    BalanceSheetSnapshot,
    EvidenceBundle,
    EvidenceItem,
    ProfitAndLossSnapshot,
    ReconciliationSnapshot,
)


@pytest.fixture
def period_end() -> date:
    return date(2025, 12, 31)


@pytest.fixture
def make_balance_sheet(period_end):
    def _make(*, accounts, currency: str = "USD") -> BalanceSheetSnapshot:
        return BalanceSheetSnapshot(as_of_date=period_end, currency=currency, accounts=accounts)

    return _make


@pytest.fixture
def make_profit_and_loss(period_end):
    def _make(*, revenue=None, currency: str = "USD") -> ProfitAndLossSnapshot | None:
        if revenue is None:
            return None
        return ProfitAndLossSnapshot(
            period_start=date(period_end.year, period_end.month, 1),
            period_end=period_end,
            currency=currency,
            totals={"revenue": revenue},
        )

    return _make


@pytest.fixture
def make_evidence_bundle(period_end):
    def _make(*, evidence_type: str, amount=None, source: str = "fixture") -> EvidenceBundle:
        if amount is None:
            return EvidenceBundle(items=[])
        return EvidenceBundle(
            items=[
                EvidenceItem(
                    evidence_type=evidence_type,
                    source=source,
                    as_of_date=period_end,
                    amount=amount,
                )
            ]
        )

    return _make


@pytest.fixture
def make_reconciliation_snapshot(period_end):
    def _make(
        *,
        account_ref: str,
        account_name: str,
        statement_end_date=None,
        statement_ending_balance=None,
        book_balance_as_of_statement_end=None,
        book_balance_as_of_period_end=None,
        meta=None,
        source: str = "fixture",
    ) -> ReconciliationSnapshot:
        return ReconciliationSnapshot(
            account_ref=account_ref,
            account_name=account_name,
            statement_end_date=statement_end_date or period_end,
            statement_ending_balance=statement_ending_balance,
            book_balance_as_of_statement_end=book_balance_as_of_statement_end,
            book_balance_as_of_period_end=book_balance_as_of_period_end,
            source=source,
            meta=meta or {},
        )

    return _make


@pytest.fixture
def make_ctx(period_end):
    def _make(
        *,
        balance_sheet: BalanceSheetSnapshot,
        client_rules: dict,
        profit_and_loss: ProfitAndLossSnapshot | None = None,
        evidence: EvidenceBundle | None = None,
        reconciliations: tuple[ReconciliationSnapshot, ...] = (),
    ) -> RuleContext:
        cfg = ClientRulesConfig(rules=client_rules)
        return RuleContext(
            period_end=period_end,
            balance_sheet=balance_sheet,
            profit_and_loss=profit_and_loss,
            evidence=evidence or EvidenceBundle(),
            reconciliations=reconciliations,
            client_config=cfg,
        )

    return _make
