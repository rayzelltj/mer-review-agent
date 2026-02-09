from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_clearing_accounts_non_sales_zero import (
    BS_CLEARING_ACCOUNTS_NON_SALES_ZERO,
)


def test_non_sales_clearing_accounts_fail_when_non_zero(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Payroll Clearing",
                "type": "Fixed Asset",
                "balance": "10",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_NON_SALES_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-NON-SALES-ZERO": {}})
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH


def test_non_sales_clearing_accounts_pass_when_zero(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Payroll Clearing",
                "type": "Fixed Asset",
                "balance": "0",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_NON_SALES_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-NON-SALES-ZERO": {}})
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_non_sales_clearing_accounts_not_applicable_when_only_sales(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Etsy Clearing",
                "type": "Bank",
                "balance": "50",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_NON_SALES_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-NON-SALES-ZERO": {}})
    )
    assert res.status == RuleStatus.NOT_APPLICABLE


def test_non_sales_clearing_accounts_needs_review_when_type_missing(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Payroll Clearing",
                "balance": "0",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_NON_SALES_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-NON-SALES-ZERO": {}})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
