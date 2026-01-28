from decimal import Decimal

from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_undeposited_funds_zero import BS_UNDEPOSITED_FUNDS_ZERO


def test_undeposited_funds_needs_review_when_not_configured(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(accounts=[{"account_ref": "U1", "name": "Undeposited Funds", "balance": "10"}])
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, client_rules={"BS-UNDEPOSITED-FUNDS-ZERO": {}})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_undeposited_funds_warn_within_configured_threshold(make_balance_sheet, make_profit_and_loss, make_ctx):
    pnl = make_profit_and_loss(revenue=Decimal("100000"))
    rule_cfg = {
        "BS-UNDEPOSITED-FUNDS-ZERO": {
            "accounts": [
                {
                    "account_ref": "U1",
                    "account_name": "Undeposited Funds",
                    "threshold": {"floor_amount": "25", "pct_of_revenue": "0.0005"},
                }
            ]
        }
    }
    # allowed=max(25,50)=50 -> 40 => WARN
    bs = make_balance_sheet(accounts=[{"account_ref": "U1", "name": "Undeposited Funds", "balance": "40"}])
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, profit_and_loss=pnl, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.WARN
    assert res.severity == Severity.LOW
    assert "Undeposited Funds" in res.summary
    assert "40" in res.summary


def test_undeposited_funds_fail_outside_threshold(make_balance_sheet, make_profit_and_loss, make_ctx):
    pnl = make_profit_and_loss(revenue=Decimal("100000"))
    rule_cfg = {
        "BS-UNDEPOSITED-FUNDS-ZERO": {
            "accounts": [
                {
                    "account_ref": "U1",
                    "account_name": "Undeposited Funds",
                    "threshold": {"floor_amount": "25", "pct_of_revenue": "0"},
                }
            ]
        }
    }
    bs = make_balance_sheet(accounts=[{"account_ref": "U1", "name": "Undeposited Funds", "balance": "40"}])
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, profit_and_loss=pnl, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH


def test_undeposited_funds_needs_review_when_threshold_unconfigured(make_balance_sheet, make_ctx):
    rule_cfg = {
        "BS-UNDEPOSITED-FUNDS-ZERO": {
            "accounts": [{"account_ref": "U1", "account_name": "Undeposited Funds"}]
        }
    }
    bs = make_balance_sheet(accounts=[{"account_ref": "U1", "name": "Undeposited Funds", "balance": "1"}])
    res = BS_UNDEPOSITED_FUNDS_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert res.details[0].values.get("threshold_configured") is False
