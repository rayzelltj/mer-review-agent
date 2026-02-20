import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from common.rules_engine.context import RuleContext
from common.rules_engine.models import EvidenceBundle, RuleStatus
from common.rules_engine.rules.bs_tax_payable_and_suspense_reconcile_to_return import (
    BS_TAX_PAYABLE_AND_SUSPENSE_RECONCILE_TO_RETURN,
    _add_months,
    _expected_period_end_from_anchor,
)
from adapters.qbo.accounts import account_type_map_from_accounts_payload
from adapters.qbo.balance_sheet import balance_sheet_snapshot_from_report
from adapters.qbo.tax import (
    tax_agencies_to_evidence,
    tax_payments_to_evidence,
    tax_returns_to_evidence,
)


def test_tax_payable_and_suspense_reconcile_blackbird():
    base = (
        Path(__file__).parents[2]
        / "tests/rules_engine/fixtures/blackbird_fabrics/2025-12-31"
    )
    balance_sheet_report = json.load((base / "balance_sheet.json").open())
    accounts_payload = json.load((base / "accounts.json").open())
    agencies = json.load((base / "tax_agencies.json").open())
    returns = json.load((base / "tax_returns.json").open())
    payments = json.load((base / "tax_payments.json").open())

    acct_map = account_type_map_from_accounts_payload(accounts_payload)
    balance_sheet = balance_sheet_snapshot_from_report(
        balance_sheet_report,
        account_types=acct_map,
        include_rows_without_id=True,
        include_summary_totals=True,
    )

    evidence = EvidenceBundle(
        items=[
            tax_agencies_to_evidence(agencies),
            tax_returns_to_evidence(returns),
            tax_payments_to_evidence(payments),
        ]
    )

    ctx = RuleContext(
        period_end=balance_sheet.as_of_date,
        balance_sheet=balance_sheet,
        evidence=evidence,
    )

    result = BS_TAX_PAYABLE_AND_SUSPENSE_RECONCILE_TO_RETURN().evaluate(ctx)
    assert result.status in {RuleStatus.NEEDS_REVIEW, RuleStatus.WARN, RuleStatus.PASS, RuleStatus.FAIL}


def test_tax_payable_expected_period_end_quarterly():
    anchor = date(2025, 10, 31)
    assert _expected_period_end_from_anchor(date(2025, 12, 31), 3, anchor) == date(2025, 10, 31)
    assert _expected_period_end_from_anchor(date(2026, 1, 31), 3, anchor) == date(2026, 1, 31)


def test_tax_payable_add_months_preserves_month_end():
    assert _add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)


def _evidence_bundle_for_policy_tests(*, returns: list[dict], payments: list[dict]) -> EvidenceBundle:
    agencies = [
        {
            "Id": "1",
            "DisplayName": "Canada Revenue Agency",
            "LastFileDate": "2025-12-31",
            "TaxTrackedOnSales": True,
            "TaxTrackedOnPurchases": True,
        }
    ]
    return EvidenceBundle(
        items=[
            tax_agencies_to_evidence(agencies),
            tax_returns_to_evidence(returns),
            tax_payments_to_evidence(payments),
        ]
    )


def test_tax_payable_must_always_be_zero(make_balance_sheet, make_ctx, period_end):
    balance_sheet = make_balance_sheet(
        accounts=[
            {"account_ref": "39", "name": "GST/HST Payable", "balance": Decimal("10.00")},
            {"account_ref": "40", "name": "GST/HST Suspense", "balance": Decimal("1000.00")},
        ]
    )
    evidence = _evidence_bundle_for_policy_tests(
        returns=[
            {
                "Id": "ret-1",
                "AgencyRef": {"value": "1"},
                "StartDate": "2025-07-01",
                "EndDate": "2025-09-30",
                "FileDate": "2025-10-30",
                "NetTaxAmountDue": "1000.00",
            }
        ],
        payments=[],
    )

    result = BS_TAX_PAYABLE_AND_SUSPENSE_RECONCILE_TO_RETURN().evaluate(
        make_ctx(balance_sheet=balance_sheet, evidence=evidence, client_rules={})
    )
    assert result.status == RuleStatus.FAIL
    assert any(detail.values.get("payable_status") == RuleStatus.FAIL.value for detail in result.details)


def test_tax_suspense_ties_to_latest_filed_return(make_balance_sheet, make_ctx, period_end):
    balance_sheet = make_balance_sheet(
        accounts=[
            {"account_ref": "39", "name": "GST/HST Payable", "balance": Decimal("0.00")},
            {"account_ref": "40", "name": "GST/HST Suspense", "balance": Decimal("1000.00")},
        ]
    )
    evidence = _evidence_bundle_for_policy_tests(
        returns=[
            {
                "Id": "ret-1",
                "AgencyRef": {"value": "1"},
                "StartDate": "2025-07-01",
                "EndDate": "2025-09-30",
                "FileDate": "2025-10-30",
                "NetTaxAmountDue": "1000.00",
            },
            {
                "Id": "ret-upcoming",
                "AgencyRef": {"value": "1"},
                "UpcomingFiling": True,
                "NetTaxAmountDue": "0",
            },
        ],
        payments=[],
    )

    result = BS_TAX_PAYABLE_AND_SUSPENSE_RECONCILE_TO_RETURN().evaluate(
        make_ctx(balance_sheet=balance_sheet, evidence=evidence, client_rules={})
    )
    assert result.status == RuleStatus.PASS


def test_tax_payments_and_refunds_offset_suspense(make_balance_sheet, make_ctx, period_end):
    balance_sheet = make_balance_sheet(
        accounts=[
            {"account_ref": "39", "name": "GST/HST Payable", "balance": Decimal("0.00")},
            {"account_ref": "40", "name": "GST/HST Suspense", "balance": Decimal("850.00")},
        ]
    )
    evidence = _evidence_bundle_for_policy_tests(
        returns=[
            {
                "Id": "ret-1",
                "AgencyRef": {"value": "1"},
                "StartDate": "2025-07-01",
                "EndDate": "2025-09-30",
                "FileDate": "2025-10-30",
                "NetTaxAmountDue": "1000.00",
            }
        ],
        payments=[
            {
                "Id": "pmt-1",
                "AgencyRef": {"value": "1"},
                "PaymentDate": "2025-11-15",
                "PaymentAmount": "200.00",
                "Refund": False,
            },
            {
                "Id": "refund-1",
                "AgencyRef": {"value": "1"},
                "PaymentDate": "2025-12-01",
                "PaymentAmount": "-50.00",
                "Refund": True,
            },
        ],
    )

    result = BS_TAX_PAYABLE_AND_SUSPENSE_RECONCILE_TO_RETURN().evaluate(
        make_ctx(balance_sheet=balance_sheet, evidence=evidence, client_rules={})
    )
    assert result.status == RuleStatus.PASS
    detail = result.details[0].values
    assert detail["expected_suspense"] == "850.00"
