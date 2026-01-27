from decimal import Decimal

from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_clearing_accounts_zero import BS_CLEARING_ACCOUNTS_ZERO


def test_clearing_accounts_zero_pass_warn_fail_severity(
    make_balance_sheet, make_profit_and_loss, make_ctx, period_end
):
    pnl = make_profit_and_loss(revenue=Decimal("100000"))
    rule_cfg = {
        "BS-CLEARING-ACCOUNTS-ZERO": {
            "accounts": [
                {
                    "account_ref": "A1",
                    "account_name": "Clearing - Payroll",
                    "threshold": {"floor_amount": "50", "pct_of_revenue": "0.001"},
                }
            ]
        }
    }

    # PASS
    bs = make_balance_sheet(accounts=[{"account_ref": "A1", "name": "Clearing - Payroll", "balance": "0"}])
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, profit_and_loss=pnl, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO
    assert period_end.isoformat() in res.summary

    # WARN (allowed = max(50, 100000*0.001=100) => 100)
    bs = make_balance_sheet(accounts=[{"account_ref": "A1", "name": "Clearing - Payroll", "balance": "80"}])
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, profit_and_loss=pnl, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.WARN
    assert res.severity == Severity.LOW
    assert "Clearing - Payroll" in res.summary
    assert "80" in res.summary

    # FAIL
    bs = make_balance_sheet(accounts=[{"account_ref": "A1", "name": "Clearing - Payroll", "balance": "120"}])
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(
        make_ctx(balance_sheet=bs, profit_and_loss=pnl, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH
    assert "Clearing - Payroll" in res.summary


def test_clearing_accounts_missing_account_needs_review(make_balance_sheet, make_ctx):
    rule_cfg = {
        "BS-CLEARING-ACCOUNTS-ZERO": {
            "accounts": [{"account_ref": "A1", "account_name": "Clearing - Payroll"}]
        }
    }
    bs = make_balance_sheet(accounts=[])
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert res.details and res.details[0].key == "A1"


def test_clearing_accounts_needs_review_when_not_configured(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-CLEARING-ACCOUNTS-ZERO": {}}
    bs = make_balance_sheet(accounts=[{"account_ref": "A1", "name": "Payroll Clearing", "balance": "10"}])
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_clearing_accounts_name_inference_when_enabled(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-CLEARING-ACCOUNTS-ZERO": {"allow_name_inference": True}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "A1", "name": "Payroll Clearing", "balance": "0"},
            {"account_ref": "A2", "name": "Other clearing", "balance": "10"},
            {"account_ref": "A3", "name": "Cash", "balance": "999"},
        ]
    )
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    # With no thresholds configured, non-zero balances default to WARN (unconfigured_threshold_policy).
    assert res.status == RuleStatus.WARN
    evaluated_keys = {d.key for d in res.details}
    assert evaluated_keys == {"A1", "A2"}
    assert any(d.values.get("threshold_configured") is False for d in res.details)


def test_clearing_accounts_rounding_boundary_quantizes(make_balance_sheet, make_ctx):
    rule_cfg = {
        "BS-CLEARING-ACCOUNTS-ZERO": {
            "accounts": [{"account_ref": "A1", "account_name": "Clearing"}],
            "amount_quantize": "0.01",
        }
    }
    bs = make_balance_sheet(accounts=[{"account_ref": "A1", "name": "Clearing", "balance": "0.004"}])
    res = BS_CLEARING_ACCOUNTS_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.PASS
