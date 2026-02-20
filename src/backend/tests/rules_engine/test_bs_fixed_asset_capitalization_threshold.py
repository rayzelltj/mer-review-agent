from datetime import date
from decimal import Decimal

from common.rules_engine.models import BalanceSheetSnapshot, EvidenceBundle, EvidenceItem, RuleStatus
from common.rules_engine.rules.bs_fixed_asset_capitalization_threshold import (
    BS_FIXED_ASSET_CAPITALIZATION_THRESHOLD,
)


def _fixed_asset_pnl_evidence(period_end, lines):
    return EvidenceItem(
        evidence_type="qbo_pnl_expense_monthly",
        source="fixture",
        as_of_date=period_end,
        meta={
            "current_period_end": period_end.isoformat(),
            "prior_period_end": date(2025, 11, 30).isoformat(),
            "lines": lines,
        },
    )


def _kyc_threshold_evidence(period_end):
    return EvidenceItem(
        evidence_type="kyc_profile",
        source="fixture",
        as_of_date=period_end,
        meta={
            "fixed_assets": (
                "Capitalization threshold for this client is total expense greater than $1,000."
            )
        },
    )


def _ledger_evidence(period_end, *, amount: str):
    return EvidenceItem(
        evidence_type="qbo_fixed_asset_ledger_transactions",
        source="fixture",
        as_of_date=period_end,
        meta={
            "account_ref": "A1",
            "transactions": [
                {
                    "txn_date": period_end.replace(day=15).isoformat(),
                    "amount": amount,
                    "description": "Equipment purchase",
                    "txn_type": "Bill",
                }
            ],
        },
    )


def _balance_sheet(accounts):
    return BalanceSheetSnapshot(
        as_of_date=date(2025, 12, 31),
        currency="USD",
        accounts=accounts,
    )


def test_fixed_asset_capitalization_threshold_pass(make_ctx):
    period_end = date(2025, 12, 31)
    bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": "5500.00",
            }
        ]
    )
    prior_bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": "4000.00",
            }
        ]
    ).model_copy(update={"as_of_date": date(2025, 11, 30)})

    evidence = EvidenceBundle(
        items=[
            _kyc_threshold_evidence(period_end),
            _ledger_evidence(period_end, amount="1500.00"),
            _fixed_asset_pnl_evidence(
                period_end,
                lines=[
                    {"name": "Advertising", "current_amount": "100.00", "prior_amount": "95.00"},
                    {"name": "Payroll Expenses", "current_amount": "500.00", "prior_amount": "300.00"},
                ],
            ),
        ]
    )

    result = BS_FIXED_ASSET_CAPITALIZATION_THRESHOLD().evaluate(
        make_ctx(
            balance_sheet=bs,
            prior_balance_sheets=(prior_bs,),
            evidence=evidence,
            client_rules={},
        )
    )

    assert result.status == RuleStatus.PASS


def test_fixed_asset_capitalization_threshold_fails_on_below_threshold_addition(make_ctx):
    period_end = date(2025, 12, 31)
    bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": "5000.00",
            }
        ]
    )
    prior_bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": "4000.00",
            }
        ]
    ).model_copy(update={"as_of_date": date(2025, 11, 30)})

    evidence = EvidenceBundle(
        items=[
            _kyc_threshold_evidence(period_end),
            _ledger_evidence(period_end, amount="800.00"),
            _fixed_asset_pnl_evidence(
                period_end,
                lines=[{"name": "Advertising", "current_amount": "100.00", "prior_amount": "100.00"}],
            ),
        ]
    )

    result = BS_FIXED_ASSET_CAPITALIZATION_THRESHOLD().evaluate(
        make_ctx(
            balance_sheet=bs,
            prior_balance_sheets=(prior_bs,),
            evidence=evidence,
            client_rules={},
        )
    )

    assert result.status == RuleStatus.FAIL
    assert any(
        detail.values.get("sub_rule") == "fixed_asset_increment_threshold"
        and detail.values.get("status") == RuleStatus.FAIL.value
        for detail in result.details
    )


def test_fixed_asset_capitalization_threshold_warns_on_abnormal_expense_changes(make_ctx):
    period_end = date(2025, 12, 31)
    bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": "4000.00",
            }
        ]
    )
    prior_bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": "4000.00",
            }
        ]
    ).model_copy(update={"as_of_date": date(2025, 11, 30)})

    evidence = EvidenceBundle(
        items=[
            _fixed_asset_pnl_evidence(
                period_end,
                lines=[
                    {"name": "Advertising", "current_amount": "150.00", "prior_amount": "100.00"},
                    {"name": "Payroll Taxes", "current_amount": "500.00", "prior_amount": "100.00"},
                ],
            )
        ]
    )

    result = BS_FIXED_ASSET_CAPITALIZATION_THRESHOLD().evaluate(
        make_ctx(
            balance_sheet=bs,
            prior_balance_sheets=(prior_bs,),
            evidence=evidence,
            client_rules={},
        )
    )

    assert result.status == RuleStatus.WARN
    assert any(detail.values.get("expense_name") == "Advertising" for detail in result.details)
    assert all(
        detail.values.get("expense_name") != "Payroll Taxes"
        for detail in result.details
        if isinstance(detail.values.get("expense_name"), str)
    )


def test_fixed_asset_capitalization_threshold_needs_review_when_kyc_threshold_missing(make_ctx):
    period_end = date(2025, 12, 31)
    bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": Decimal("5000.00"),
            }
        ]
    )
    prior_bs = _balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Computer Equipment",
                "type": "Fixed Asset",
                "balance": Decimal("4000.00"),
            }
        ]
    ).model_copy(update={"as_of_date": date(2025, 11, 30)})

    evidence = EvidenceBundle(
        items=[
            _ledger_evidence(period_end, amount="1500.00"),
            _fixed_asset_pnl_evidence(
                period_end,
                lines=[{"name": "Advertising", "current_amount": "100.00", "prior_amount": "100.00"}],
            ),
        ]
    )

    result = BS_FIXED_ASSET_CAPITALIZATION_THRESHOLD().evaluate(
        make_ctx(
            balance_sheet=bs,
            prior_balance_sheets=(prior_bs,),
            evidence=evidence,
            client_rules={},
        )
    )

    assert result.status == RuleStatus.NEEDS_REVIEW
    assert any(detail.key == "fixed_assets_kyc_threshold_missing" for detail in result.details)
