from datetime import date
from decimal import Decimal

from common.rules_engine.models import BalanceSheetSnapshot, ProfitAndLossSnapshot, RuleStatus, Severity
from common.rules_engine.rules.bs_undeposited_funds_zero import BS_UNDEPOSITED_FUNDS_ZERO


def _platform_pnl(*, period_end, platform_name: str, amount: Decimal) -> ProfitAndLossSnapshot:
    return ProfitAndLossSnapshot(
        period_start=date(period_end.year, period_end.month, 1),
        period_end=period_end,
        currency="USD",
        totals={
            "revenue": amount,
            f"income_line:Sales - {platform_name}": amount,
        },
    )


def test_undeposited_funds_warn_and_fail_with_platform_plus_prior_variance(
    make_balance_sheet, make_ctx, period_end
):
    rule_cfg = {"BS-UNDEPOSITED-FUNDS-ZERO": {}}
    pnl = _platform_pnl(period_end=period_end, platform_name="Shopify", amount=Decimal("2000"))
    prior_bs = BalanceSheetSnapshot(
        as_of_date=date(2025, 11, 30),
        currency="USD",
        accounts=[
            {
                "account_ref": "U1",
                "name": "Shopify Undeposited Funds",
                "type": "Other Current Asset",
                "balance": "50",
            }
        ],
    )

    bs_warn = make_balance_sheet(
        accounts=[
            {
                "account_ref": "U1",
                "name": "Shopify Undeposited Funds",
                "type": "Other Current Asset",
                "balance": "201.5",
            }
        ]
    )
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(
            balance_sheet=bs_warn,
            client_rules=rule_cfg,
            profit_and_loss=pnl,
            prior_balance_sheets=(prior_bs,),
        )
    )
    assert res.status == RuleStatus.WARN
    assert res.severity == Severity.LOW
    detail = res.details[0].values
    assert Decimal(detail["platform_revenue"]) == Decimal("2000")
    assert Decimal(detail["previous_month_variance_value"]) == Decimal("50")
    assert Decimal(detail["allowed_variance"]) == Decimal("201.5")
    assert detail["threshold_source"] == "platform_revenue_plus_previous_month_variance"

    bs_fail = make_balance_sheet(
        accounts=[
            {
                "account_ref": "U1",
                "name": "Shopify Undeposited Funds",
                "type": "Other Current Asset",
                "balance": "202",
            }
        ]
    )
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(
            balance_sheet=bs_fail,
            client_rules=rule_cfg,
            profit_and_loss=pnl,
            prior_balance_sheets=(prior_bs,),
        )
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH


def test_undeposited_funds_generic_name_requires_review(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "U1",
                "name": "Undeposited Funds",
                "type": "Other Current Asset",
                "balance": "0",
            }
        ]
    )
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-UNDEPOSITED-FUNDS-ZERO": {}})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert res.details[0].values["platform_name_missing"] is True
    assert "GENERIC UNDEPOSITED ACCOUNT" in (res.details[0].values.get("review_comment") or "")


def test_undeposited_funds_asset_scope_only(make_balance_sheet, make_ctx, period_end):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "U1",
                "name": "Shopify Undeposited Funds",
                "type": "Other Current Asset",
                "balance": "0",
            },
            {
                "account_ref": "U2",
                "name": "Shopify Undeposited Funds Liability",
                "type": "Accounts Payable",
                "balance": "250",
            },
        ]
    )
    pnl = _platform_pnl(period_end=period_end, platform_name="Shopify", amount=Decimal("500"))
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-UNDEPOSITED-FUNDS-ZERO": {}}, profit_and_loss=pnl)
    )
    assert res.status == RuleStatus.PASS
    assert {d.key for d in res.details} == {"U1"}


def test_undeposited_funds_missing_platform_mapping_needs_review(make_balance_sheet, make_ctx, period_end):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "U1",
                "name": "Shopify Undeposited Funds",
                "type": "Other Current Asset",
                "balance": "10",
            }
        ]
    )
    pnl = _platform_pnl(period_end=period_end, platform_name="Etsy", amount=Decimal("100"))
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-UNDEPOSITED-FUNDS-ZERO": {}}, profit_and_loss=pnl)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.details[0].values["platform_revenue_missing"] is True


def test_undeposited_funds_not_applicable_when_no_accounts(make_balance_sheet, make_ctx):
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(
            balance_sheet=make_balance_sheet(
                accounts=[{"account_ref": "C1", "name": "Cash", "type": "Bank", "balance": "10"}]
            ),
            client_rules={"BS-UNDEPOSITED-FUNDS-ZERO": {}},
        )
    )
    assert res.status == RuleStatus.NOT_APPLICABLE
