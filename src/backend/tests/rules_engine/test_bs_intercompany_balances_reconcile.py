from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_intercompany_balances_reconcile import (
    BS_INTERCOMPANY_BALANCES_RECONCILE,
)


def test_intercompany_loan_pass_when_balances_match(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-INTERCOMPANY-BALANCES-RECONCILE": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "L1", "name": "Intercompany Loan Company B", "type": "Asset", "balance": "1000"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={
                    "items": [
                        {
                            "company": "Company B",
                            "account_name": "Intercompany Loan Company A",
                            "balance": "-1000",
                        }
                    ]
                },
            )
        ]
    )
    res = BS_INTERCOMPANY_BALANCES_RECONCILE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_intercompany_loan_needs_review_when_missing_counterparty(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-INTERCOMPANY-BALANCES-RECONCILE": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "L1", "name": "Loan from Company C", "type": "Liability", "balance": "500"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={
                    "items": [
                        {
                            "company": "Company B",
                            "account_name": "Loan to Company A",
                            "balance": "500",
                        }
                    ]
                },
            )
        ]
    )
    res = BS_INTERCOMPANY_BALANCES_RECONCILE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_intercompany_loan_needs_review_when_mismatch(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-INTERCOMPANY-BALANCES-RECONCILE": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "L1", "name": "Due to Company D (Loan)", "type": "Liability", "balance": "700"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={
                    "items": [
                        {
                            "company": "Company D",
                            "account_name": "Due from Company A (Loan)",
                            "balance": "500",
                        }
                    ]
                },
            )
        ]
    )
    res = BS_INTERCOMPANY_BALANCES_RECONCILE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_intercompany_loan_not_applicable_when_no_accounts(make_balance_sheet, make_ctx, period_end):
    rule_cfg = {"BS-INTERCOMPANY-BALANCES-RECONCILE": {}}
    bs = make_balance_sheet(accounts=[])
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="intercompany_balance_sheet",
                source="fixture",
                as_of_date=period_end,
                amount="0",
                meta={
                    "items": [
                        {
                            "company": "Company B",
                            "account_name": "Intercompany Loan Company A",
                            "balance": "1000",
                        }
                    ]
                },
            )
        ]
    )
    res = BS_INTERCOMPANY_BALANCES_RECONCILE().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NOT_APPLICABLE
