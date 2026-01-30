from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_investment_balance_match import (
    BS_INVESTMENT_BALANCE_MATCH,
)


def test_investment_balance_pass_when_exact_match(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-INVESTMENT-BALANCE-MATCH": {"account_ref": "I1", "account_name": "Investments"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "I1", "name": "Investments", "type": "Asset", "balance": "2500"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="investment_statement_balance",
                source="fixture",
                as_of_date=period_end,
                amount="2500",
            )
        ]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_investment_balance_fail_when_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-INVESTMENT-BALANCE-MATCH": {"account_ref": "I1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "I1", "name": "Investments", "type": "Asset", "balance": "2500"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="investment_statement_balance",
                source="fixture",
                as_of_date=period_end,
                amount="2000",
            )
        ]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL


def test_investment_balance_needs_review_when_evidence_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-INVESTMENT-BALANCE-MATCH": {"account_ref": "I1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "I1", "name": "Investments", "type": "Asset", "balance": "2500"}]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=EvidenceBundle(items=[]), client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_investment_balance_needs_review_when_evidence_date_mismatch(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-INVESTMENT-BALANCE-MATCH": {"account_ref": "I1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "I1", "name": "Investments", "type": "Asset", "balance": "2500"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="investment_statement_balance",
                source="fixture",
                as_of_date=date(2025, 12, 30),
                amount="2500",
            )
        ]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_investment_balance_not_applicable_when_account_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-INVESTMENT-BALANCE-MATCH": {"account_ref": "I1"}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="investment_statement_balance",
                source="fixture",
                as_of_date=date(2025, 12, 31),
                amount="2500",
            )
        ]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE


def test_investment_balance_infers_by_name_when_configured(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {
        "BS-INVESTMENT-BALANCE-MATCH": {"allow_name_inference": True, "account_name_match": "investment"}
    }
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "I1", "name": "Investment Account", "type": "Asset", "balance": "2500"},
            {"account_ref": "O1", "name": "Operating", "type": "Bank", "balance": "10"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="investment_statement_balance",
                source="fixture",
                as_of_date=period_end,
                amount="2500",
            )
        ]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.details[0].values.get("inferred_by_name_match") is True


def test_investment_balance_needs_review_when_multiple_name_matches(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {
        "BS-INVESTMENT-BALANCE-MATCH": {"allow_name_inference": True, "account_name_match": "investment"}
    }
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "I1", "name": "Investment Account A", "type": "Asset", "balance": "2500"},
            {"account_ref": "I2", "name": "Investment Account B", "type": "Asset", "balance": "3000"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="investment_statement_balance",
                source="fixture",
                as_of_date=period_end,
                amount="5500",
            )
        ]
    )
    res = BS_INVESTMENT_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
