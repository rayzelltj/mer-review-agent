from __future__ import annotations

from datetime import date
from decimal import Decimal

from common.rules_engine.config import ClientRulesConfig
from common.rules_engine.context import RuleContext
from common.rules_engine.models import AccountBalance, BalanceSheetSnapshot, RuleStatus
from common.rules_engine.rules.bs_balance_unchanged_prior_month import (
    BS_BALANCE_UNCHANGED_PRIOR_MONTH,
)


def _snapshot(*, as_of_date: date, accounts: list[dict[str, str]]) -> BalanceSheetSnapshot:
    return BalanceSheetSnapshot(
        as_of_date=as_of_date,
        accounts=[
            AccountBalance(
                account_ref=str(item["account_ref"]),
                name=str(item["name"]),
                balance=Decimal(str(item["balance"])),
            )
            for item in accounts
        ],
    )


def _ctx(
    *,
    period_end: date,
    balance_sheet: BalanceSheetSnapshot,
    prior_balance_sheets: tuple[BalanceSheetSnapshot, ...] = (),
    rule_cfg: dict | None = None,
) -> RuleContext:
    return RuleContext(
        period_end=period_end,
        balance_sheet=balance_sheet,
        prior_balance_sheets=prior_balance_sheets,
        client_config=ClientRulesConfig(
            rules={"BS-BALANCE-UNCHANGED-PRIOR-MONTH": rule_cfg or {}}
        ),
    )


def test_balance_unchanged_not_applicable_when_prior_snapshot_missing():
    period_end = date(2025, 12, 31)
    current = _snapshot(
        as_of_date=period_end,
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "100"}],
    )

    result = BS_BALANCE_UNCHANGED_PRIOR_MONTH().evaluate(
        _ctx(period_end=period_end, balance_sheet=current)
    )

    assert result.status == RuleStatus.NOT_APPLICABLE
    assert "Missing prior month Balance Sheet snapshot" in result.summary


def test_balance_unchanged_warns_for_matching_leaf_balances():
    period_end = date(2025, 12, 31)
    current = _snapshot(
        as_of_date=period_end,
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "100"}],
    )
    prior = _snapshot(
        as_of_date=date(2025, 11, 30),
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "100"}],
    )

    result = BS_BALANCE_UNCHANGED_PRIOR_MONTH().evaluate(
        _ctx(period_end=period_end, balance_sheet=current, prior_balance_sheets=(prior,))
    )

    assert result.status == RuleStatus.WARN
    assert len(result.details) == 1
    assert result.details[0].values.get("flag") == "SAME"


def test_balance_unchanged_passes_when_balances_changed():
    period_end = date(2025, 12, 31)
    current = _snapshot(
        as_of_date=period_end,
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "120"}],
    )
    prior = _snapshot(
        as_of_date=date(2025, 11, 30),
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "100"}],
    )

    result = BS_BALANCE_UNCHANGED_PRIOR_MONTH().evaluate(
        _ctx(period_end=period_end, balance_sheet=current, prior_balance_sheets=(prior,))
    )

    assert result.status == RuleStatus.PASS


def test_balance_unchanged_ignores_zero_matches_when_configured():
    period_end = date(2025, 12, 31)
    current = _snapshot(
        as_of_date=period_end,
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "0"}],
    )
    prior = _snapshot(
        as_of_date=date(2025, 11, 30),
        accounts=[{"account_ref": "A1", "name": "Cash", "balance": "0"}],
    )

    result = BS_BALANCE_UNCHANGED_PRIOR_MONTH().evaluate(
        _ctx(
            period_end=period_end,
            balance_sheet=current,
            prior_balance_sheets=(prior,),
            rule_cfg={"include_zero_balances": False},
        )
    )

    assert result.status == RuleStatus.PASS
