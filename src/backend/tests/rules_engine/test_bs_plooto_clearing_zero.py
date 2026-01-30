from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_plooto_clearing_zero import BS_PLOOTO_CLEARING_ZERO


def test_plooto_clearing_pass_when_zero_balance(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-CLEARING-ZERO": {"account_ref": "C1", "account_name": "Plooto Clearing"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "C1", "name": "Plooto Clearing", "type": "Bank", "balance": "0"}]
    )
    res = BS_PLOOTO_CLEARING_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_plooto_clearing_fail_when_non_zero(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-CLEARING-ZERO": {"account_ref": "C1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "C1", "name": "Plooto Clearing", "type": "Bank", "balance": "10"}]
    )
    res = BS_PLOOTO_CLEARING_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH


def test_plooto_clearing_not_applicable_when_no_account_found(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-CLEARING-ZERO": {"allow_name_inference": True}}
    bs = make_balance_sheet(accounts=[])
    res = BS_PLOOTO_CLEARING_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NOT_APPLICABLE


def test_plooto_clearing_needs_review_when_configured_account_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-CLEARING-ZERO": {"account_ref": "C1"}}
    bs = make_balance_sheet(accounts=[])
    res = BS_PLOOTO_CLEARING_ZERO().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW
