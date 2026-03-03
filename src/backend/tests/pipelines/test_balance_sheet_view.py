from __future__ import annotations

from datetime import date
from decimal import Decimal

from common.rules_engine.models import (
    AccountBalance,
    BalanceSheetSnapshot,
    RuleResult,
    RuleResultDetail,
    RuleStatus,
    Severity,
)
from pipelines.balance_sheet_view import build_balance_sheet_view


def _snapshot(as_of_date: date, accounts: list[tuple[str, str, Decimal]]) -> BalanceSheetSnapshot:
    return BalanceSheetSnapshot(
        as_of_date=as_of_date,
        currency="CAD",
        accounts=[
            AccountBalance(account_ref=account_ref, name=name, balance=balance)
            for account_ref, name, balance in accounts
        ],
    )


def test_balance_sheet_view_includes_current_and_three_prior_periods():
    current = _snapshot(
        date(2025, 12, 31),
        [
            ("qbo::100", "Cash", Decimal("1200.00")),
            ("qbo::200", "Accounts Payable", Decimal("-300.00")),
        ],
    )
    prior_1 = _snapshot(
        date(2025, 11, 30),
        [
            ("qbo::100", "Cash", Decimal("1000.00")),
            ("qbo::200", "Accounts Payable", Decimal("-250.00")),
        ],
    )
    # Deliberately uses different account refs so name fallback is exercised.
    prior_2 = _snapshot(
        date(2025, 10, 31),
        [
            ("100", "Cash", Decimal("900.00")),
            ("200", "Accounts Payable", Decimal("-200.00")),
        ],
    )
    # Deliberately omits AP so missing-period handling is exercised.
    prior_3 = _snapshot(
        date(2025, 9, 30),
        [
            ("qbo::100", "Cash", Decimal("850.00")),
        ],
    )

    view = build_balance_sheet_view(
        client_id="acme",
        period_end=date(2025, 12, 31),
        balance_sheet=current,
        prior_balance_sheets=(prior_1, prior_2, prior_3),
        results=[],
    )

    assert [column["period_end"] for column in view["period_columns"]] == [
        "2025-12-31",
        "2025-11-30",
        "2025-10-31",
        "2025-09-30",
    ]

    rows = {row["account"]["account_ref"]: row for row in view["accounts"]}
    assert rows["qbo::100"]["balances_by_period"] == {
        "2025-12-31": "1200.00",
        "2025-11-30": "1000.00",
        "2025-10-31": "900.00",
        "2025-09-30": "850.00",
    }
    assert rows["qbo::200"]["balances_by_period"] == {
        "2025-12-31": "-300.00",
        "2025-11-30": "-250.00",
        "2025-10-31": "-200.00",
        "2025-09-30": None,
    }
    assert rows["qbo::100"]["status"] == "NOT_APPLICABLE"
    assert rows["qbo::100"]["notes"] == []


def test_account_with_multiple_rules_shows_all_notes():
    """When two rules evaluate the same account, notes should contain both summaries."""
    current = _snapshot(
        date(2025, 12, 31),
        [("qbo::100", "Etsy Clearing Account", Decimal("369.68"))],
    )
    rule_a = RuleResult(
        rule_id="BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END",
        rule_title="Bank/CC recon",
        status=RuleStatus.NEEDS_REVIEW,
        severity=Severity.HIGH,
        summary="Missing evidence for bank recon.",
        details=[
            RuleResultDetail(
                key="qbo::100",
                message="Missing evidence.",
                values={"account_name": "Etsy Clearing Account", "status": "NEEDS_REVIEW"},
            )
        ],
    )
    rule_b = RuleResult(
        rule_id="BS-CLEARING-ACCOUNTS-ZERO",
        rule_title="Clearing accounts zero",
        status=RuleStatus.WARN,
        severity=Severity.MEDIUM,
        summary="Clearing account non-zero but within variance.",
        details=[
            RuleResultDetail(
                key="qbo::100",
                message="Evaluated.",
                values={"account_name": "Etsy Clearing Account", "status": "WARN"},
            )
        ],
    )
    view = build_balance_sheet_view(
        client_id="acme",
        period_end=date(2025, 12, 31),
        balance_sheet=current,
        results=[rule_a, rule_b],
    )
    row = view["accounts"][0]
    assert row["status"] == "NEEDS_REVIEW"  # worst of the two
    assert len(row["notes"]) == 2
    rule_ids = [n["rule_id"] for n in row["notes"]]
    assert "BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END" in rule_ids
    assert "BS-CLEARING-ACCOUNTS-ZERO" in rule_ids
    assert row["notes"][0]["summary"] == "Missing evidence for bank recon."
    assert row["notes"][1]["summary"] == "Clearing account non-zero but within variance."
