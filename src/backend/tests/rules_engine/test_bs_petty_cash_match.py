from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_petty_cash_match import BS_PETTY_CASH_MATCH


def test_petty_cash_match_pass(make_balance_sheet, make_evidence_bundle, make_ctx):
    rule_cfg = {
        "BS-PETTY-CASH-MATCH": {
            "account_ref": "P1",
            "account_name": "Petty Cash",
        }
    }
    bs = make_balance_sheet(accounts=[{"account_ref": "P1", "name": "Petty Cash", "balance": "1000"}])
    ev = make_evidence_bundle(evidence_type="petty_cash_support", amount="1000")
    res = BS_PETTY_CASH_MATCH().evaluate(make_ctx(balance_sheet=bs, evidence=ev, client_rules=rule_cfg))
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_petty_cash_not_applicable_when_missing_supporting_doc(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-PETTY-CASH-MATCH": {"account_ref": "P1", "account_name": "Petty Cash"}}
    bs = make_balance_sheet(accounts=[{"account_ref": "P1", "name": "Petty Cash", "balance": "1000"}])
    res = BS_PETTY_CASH_MATCH().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert res.severity == Severity.MEDIUM
    assert period_end.isoformat() in res.summary


def test_petty_cash_not_applicable_when_missing_in_qbo(make_balance_sheet, make_evidence_bundle, make_ctx):
    rule_cfg = {"BS-PETTY-CASH-MATCH": {"account_ref": "P1", "account_name": "Petty Cash"}}
    bs = make_balance_sheet(accounts=[])
    ev = make_evidence_bundle(evidence_type="petty_cash_support", amount="1000")
    res = BS_PETTY_CASH_MATCH().evaluate(make_ctx(balance_sheet=bs, evidence=ev, client_rules=rule_cfg))
    assert res.status == RuleStatus.NOT_APPLICABLE
    assert res.severity == Severity.INFO


def test_petty_cash_fail_on_mismatch(make_balance_sheet, make_evidence_bundle, make_ctx):
    rule_cfg = {
        "BS-PETTY-CASH-MATCH": {
            "account_ref": "P1",
            "account_name": "Petty Cash",
        }
    }
    bs = make_balance_sheet(accounts=[{"account_ref": "P1", "name": "Petty Cash", "balance": "1000"}])
    ev = make_evidence_bundle(evidence_type="petty_cash_support", amount="900")
    res = BS_PETTY_CASH_MATCH().evaluate(make_ctx(balance_sheet=bs, evidence=ev, client_rules=rule_cfg))
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH
    assert "diff" in res.summary.lower()
