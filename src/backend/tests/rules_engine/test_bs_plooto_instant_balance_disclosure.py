from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_plooto_instant_balance_disclosure import (
    BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE,
)


def test_plooto_instant_pass_when_zero_balance_configured(make_balance_sheet, make_ctx):
    rule_cfg = {
        "BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {
            "account_ref": "P1",
            "account_name": "Plooto Instant",
        }
    }
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "0"}]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_plooto_instant_warn_when_non_zero_balance(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "P1", "name": "Plooto Instant", "type": "Other Current Asset", "balance": "25"}]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.WARN
    assert res.severity == Severity.LOW


def test_plooto_instant_needs_review_when_balance_sheet_account_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"account_ref": "P1"}}
    bs = make_balance_sheet(accounts=[])
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_plooto_instant_infer_by_name_when_account_ref_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE": {"allow_name_inference": True}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "P1", "name": "Plooto Instant CAD", "type": "Bank", "balance": "0"},
            {"account_ref": "P2", "name": "Operating", "type": "Bank", "balance": "100"},
        ]
    )
    res = BS_PLOOTO_INSTANT_BALANCE_DISCLOSURE().evaluate(
        make_ctx(balance_sheet=bs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.details[0].values.get("inferred_by_name_match") is True
