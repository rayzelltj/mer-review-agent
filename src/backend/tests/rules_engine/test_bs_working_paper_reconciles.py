from decimal import Decimal

from common.rules_engine.models import AccountBalance, EvidenceBundle, EvidenceItem, RuleStatus
from common.rules_engine.rules.bs_working_paper_reconciles import BS_WORKING_PAPER_RECONCILES


def test_working_paper_reconciles_pass(make_ctx, make_balance_sheet, period_end):
    balance_sheet = make_balance_sheet(
        accounts=[
            AccountBalance(
                account_ref="qbo::1",
                name="Prepaid Expenses",
                type="Other Current Asset",
                subtype="Prepaid Expenses",
                balance=Decimal("6978.74"),
            )
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="working_paper_balance",
                source="fixture",
                as_of_date=period_end,
                amount=Decimal("6978.74"),
            )
        ]
    )
    ctx = make_ctx(balance_sheet=balance_sheet, client_rules={}, evidence=evidence)
    result = BS_WORKING_PAPER_RECONCILES().evaluate(ctx)

    assert result.status == RuleStatus.PASS


def test_working_paper_reconciles_missing_evidence(make_ctx, make_balance_sheet):
    balance_sheet = make_balance_sheet(
        accounts=[
            AccountBalance(
                account_ref="qbo::1",
                name="Deferred Revenue",
                type="Other Current Liability",
                subtype="Deferred Revenue",
                balance=Decimal("100.00"),
            )
        ]
    )
    ctx = make_ctx(balance_sheet=balance_sheet, client_rules={})
    result = BS_WORKING_PAPER_RECONCILES().evaluate(ctx)

    assert result.status == RuleStatus.NEEDS_REVIEW


def test_working_paper_reconciles_mismatch_fails(make_ctx, make_balance_sheet, period_end):
    balance_sheet = make_balance_sheet(
        accounts=[
            AccountBalance(
                account_ref="qbo::1",
                name="Accruals",
                type="Other Current Liability",
                subtype="Accrued Liabilities",
                balance=Decimal("500.00"),
            )
        ]
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="working_paper_balance",
                source="fixture",
                as_of_date=period_end,
                amount=Decimal("450.00"),
            )
        ]
    )
    ctx = make_ctx(balance_sheet=balance_sheet, client_rules={}, evidence=evidence)
    result = BS_WORKING_PAPER_RECONCILES().evaluate(ctx)

    assert result.status == RuleStatus.FAIL


def test_working_paper_reconciles_not_applicable(make_ctx, make_balance_sheet):
    balance_sheet = make_balance_sheet(
        accounts=[
            AccountBalance(
                account_ref="qbo::1",
                name="Cash",
                type="Bank",
                subtype="Cash on hand",
                balance=Decimal("100.00"),
            )
        ]
    )
    ctx = make_ctx(balance_sheet=balance_sheet, client_rules={})
    result = BS_WORKING_PAPER_RECONCILES().evaluate(ctx)

    assert result.status == RuleStatus.NOT_APPLICABLE
