from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_ap_ar_intercompany_or_shareholder_paid import (
    BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID,
)


def test_intercompany_pass_when_balances_match(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "I1", "name": "Due to Company B", "type": "Liability", "balance": "1000"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": [{"counterparty": "Company B", "balance": "-1000"}]},
            )
        ]
    )
    res = BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_intercompany_needs_review_when_missing_counterparty(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "I1", "name": "Due from Company C", "type": "Asset", "balance": "500"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": [{"counterparty": "Company B", "balance": "500"}]},
            )
        ]
    )
    res = BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_intercompany_needs_review_when_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "I1", "name": "Inter-company Company D", "type": "Asset", "balance": "700"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": [{"counterparty": "Company D", "balance": "500"}]},
            )
        ]
    )
    res = BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_intercompany_needs_review_when_evidence_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "I1", "name": "Due to Company B", "type": "Liability", "balance": "1000"},
        ]
    )
    res = BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID().evaluate(
        make_ctx(balance_sheet=bs, evidence=EvidenceBundle(items=[]), client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_intercompany_not_applicable_when_no_accounts(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={"items": [{"counterparty": "Company B", "balance": "1000"}]},
            )
        ]
    )
    res = BS_AP_AR_INTERCOMPANY_OR_SHAREHOLDER_PAID().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE
