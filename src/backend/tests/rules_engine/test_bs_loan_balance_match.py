from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_loan_balance_match import BS_LOAN_BALANCE_MATCH


def test_loan_balance_pass_when_exact_match(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"account_ref": "L1", "account_name": "Loan Payable"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "L1", "name": "Loan Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="loan_schedule_balance",
                source="fixture",
                as_of_date=period_end,
                amount="1000",
            )
        ]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_loan_balance_fail_when_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"account_ref": "L1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "L1", "name": "Loan Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="loan_schedule_balance",
                source="fixture",
                as_of_date=period_end,
                amount="900",
            )
        ]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL


def test_loan_balance_needs_review_when_evidence_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"account_ref": "L1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "L1", "name": "Loan Payable", "type": "Liability", "balance": "1000"}]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=EvidenceBundle(items=[]), client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_loan_balance_needs_review_when_evidence_date_mismatch(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"account_ref": "L1"}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "L1", "name": "Loan Payable", "type": "Liability", "balance": "1000"}]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="loan_schedule_balance",
                source="fixture",
                as_of_date=date(2025, 12, 30),
                amount="1000",
            )
        ]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_loan_balance_not_applicable_when_account_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"account_ref": "L1"}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="loan_schedule_balance",
                source="fixture",
                as_of_date=date(2025, 12, 31),
                amount="1000",
            )
        ]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE


def test_loan_balance_infers_by_name_when_configured(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"allow_name_inference": True, "account_name_match": "loan"}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "L1", "name": "Loan Payable", "type": "Liability", "balance": "1000"},
            {"account_ref": "O1", "name": "Operating", "type": "Bank", "balance": "10"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="loan_schedule_balance",
                source="fixture",
                as_of_date=period_end,
                amount="1000",
            )
        ]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.details[0].values.get("inferred_by_name_match") is True


def test_loan_balance_needs_review_when_multiple_name_matches(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-LOAN-BALANCE-MATCH": {"allow_name_inference": True, "account_name_match": "loan"}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "L1", "name": "Loan Payable A", "type": "Liability", "balance": "1000"},
            {"account_ref": "L2", "name": "Loan Payable B", "type": "Liability", "balance": "500"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="loan_schedule_balance",
                source="fixture",
                as_of_date=period_end,
                amount="1500",
            )
        ]
    )
    res = BS_LOAN_BALANCE_MATCH().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
