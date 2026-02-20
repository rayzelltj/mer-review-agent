from datetime import date
from decimal import Decimal

from common.rules_engine.models import BalanceSheetSnapshot, ProfitAndLossSnapshot, RuleStatus, Severity
from common.rules_engine.rules.bs_clearing_accounts_zero import BS_CLEARING_ACCOUNTS_ZERO


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


def test_clearing_accounts_warn_and_fail_with_platform_plus_prior_variance(
    make_balance_sheet, make_ctx, period_end
):
    rule_cfg = {"BS-CLEARING-ACCOUNTS-ZERO": {}}
    pnl = _platform_pnl(period_end=period_end, platform_name="Etsy", amount=Decimal("1000"))
    prior_bs = BalanceSheetSnapshot(
        as_of_date=date(2025, 11, 30),
        currency="USD",
        accounts=[
            {
                "account_ref": "A1",
                "name": "Etsy Clearing Account",
                "type": "Bank",
                "balance": "100",
            }
        ],
    )

    bs_warn = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Etsy Clearing Account",
                "type": "Bank",
                "balance": "103",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
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
    assert Decimal(detail["platform_revenue"]) == Decimal("1000")
    assert Decimal(detail["previous_month_variance_value"]) == Decimal("100")
    assert Decimal(detail["allowed_variance"]) == Decimal("103")
    assert "0.10" in detail["allowed_variance_calculation"]
    assert "0.03" in detail["allowed_variance_calculation"]
    assert detail["threshold_source"] == "platform_revenue_plus_previous_month_variance"

    bs_fail = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Etsy Clearing Account",
                "type": "Bank",
                "balance": "104",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(
            balance_sheet=bs_fail,
            client_rules=rule_cfg,
            profit_and_loss=pnl,
            prior_balance_sheets=(prior_bs,),
        )
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH


def test_clearing_accounts_generic_name_requires_review(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Clearing Account",
                "type": "Bank",
                "balance": "0",
            }
        ]
    )
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-ZERO": {}})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert res.details[0].values["platform_name_missing"] is True
    assert "GENERIC CLEARING ACCOUNT" in (res.details[0].values.get("review_comment") or "")


def test_clearing_accounts_asset_scope_only(make_balance_sheet, make_ctx, period_end):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Etsy Clearing Account",
                "type": "Bank",
                "balance": "0",
            },
            {
                "account_ref": "A2",
                "name": "Etsy Clearing Account Liability",
                "type": "Accounts Payable",
                "balance": "999",
            },
        ]
    )
    pnl = _platform_pnl(period_end=period_end, platform_name="Etsy", amount=Decimal("1000"))
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-ZERO": {}}, profit_and_loss=pnl)
    )
    assert res.status == RuleStatus.PASS
    assert {d.key for d in res.details} == {"A1"}


def test_clearing_accounts_missing_platform_mapping_needs_review(make_balance_sheet, make_ctx, period_end):
    bs = make_balance_sheet(
        accounts=[
            {
                "account_ref": "A1",
                "name": "Etsy Clearing Account",
                "type": "Bank",
                "balance": "10",
            }
        ]
    )
    pnl = _platform_pnl(period_end=period_end, platform_name="Shopify", amount=Decimal("500"))
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-CLEARING-ACCOUNTS-ZERO": {}}, profit_and_loss=pnl)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.details[0].values["platform_revenue_missing"] is True


def test_clearing_accounts_missing_account_needs_review(make_balance_sheet, make_ctx):
    rule_cfg = {
        "BS-CLEARING-ACCOUNTS-ZERO": {
            "accounts": [{"account_ref": "A1", "account_name": "Etsy Clearing Account"}]
        }
    }
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=make_balance_sheet(accounts=[]), client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert res.details and res.details[0].key == "A1"
