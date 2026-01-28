from datetime import date

from common.rules_engine.models import EvidenceBundle, EvidenceItem
from common.rules_engine.models import RuleStatus, Severity
from common.rules_engine.rules.bs_bank_reconciled_through_period_end import (
    BS_BANK_RECONCILED_THROUGH_PERIOD_END,
)


def test_bank_reconciled_pass_when_ties_out_and_through_period_end(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"expected_accounts": ["B1"]}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "5000"}]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="5000",
            book_balance_as_of_statement_end="5000",
            book_balance_as_of_period_end="5000",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="5000",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO


def test_bank_reconciled_fail_when_statement_before_period_end(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx, period_end
):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"expected_accounts": ["B1"]}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "5000"}]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_end_date=date(2025, 11, 30),
            statement_ending_balance="5000",
            book_balance_as_of_statement_end="5000",
            book_balance_as_of_period_end="5000",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 11, 30),
                amount="5000",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL
    assert period_end.isoformat() in res.details[0].values.get("period_end", "")


def test_bank_reconciled_needs_review_when_missing_book_balance(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"expected_accounts": ["B1"]}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "5000"}]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="5000",
            book_balance_as_of_statement_end=None,
            book_balance_as_of_period_end="5000",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="5000",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_bank_reconciled_needs_review_when_missing_snapshot_for_a_balance_sheet_account(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"expected_accounts": ["B1", "CC1"]}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "5000"},
            {"account_ref": "CC1", "name": "Corporate Card", "type": "Credit Card", "balance": "0"},
        ]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="5000",
            book_balance_as_of_statement_end="5000",
            book_balance_as_of_period_end="5000",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="5000",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_bank_reconciled_needs_review_when_cannot_infer_accounts_without_types(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"expected_accounts": ["B1"]}}
    bs = make_balance_sheet(
        accounts=[{"account_ref": "B1", "name": "Checking", "type": "", "balance": "5000"}]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="5000",
            book_balance_as_of_statement_end="5000",
            book_balance_as_of_period_end="5000",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="5000",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS


def test_bank_reconciled_expected_accounts_are_enforced(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"expected_accounts": ["B2"]}}
    bs = make_balance_sheet(accounts=[])
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_bank_reconciled_infers_scope_by_type_when_no_explicit_list(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {}}
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "100"}])
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="100",
            book_balance_as_of_statement_end="100",
            book_balance_as_of_period_end="100",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="100",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS


def test_bank_reconciled_needs_review_when_inference_types_missing(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {}}
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "0"},
            {"account_ref": "A1", "name": "Some Other Account", "type": "", "balance": "0"},
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_bank_reconciled_exclude_overrides_inferred_scope(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-BANK-RECONCILED-THROUGH-PERIOD-END": {"exclude_accounts": ["B1"]}}
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "0"}])
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NOT_APPLICABLE


def test_bank_reconciled_period_end_tie_out_optional_check(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {
        "BS-BANK-RECONCILED-THROUGH-PERIOD-END": {
            "expected_accounts": ["B1"],
            "require_book_balance_as_of_period_end_ties_to_balance_sheet": True,
        }
    }
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "100"}])
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="100",
            book_balance_as_of_statement_end="100",
            book_balance_as_of_period_end="90",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="100",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL


def test_bank_reconciled_fail_when_statement_tie_has_any_difference(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {
        "BS-BANK-RECONCILED-THROUGH-PERIOD-END": {
            "expected_accounts": ["B1"],
        }
    }
    bs = make_balance_sheet(
        accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "5000"}]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance="5000",
            book_balance_as_of_statement_end="5008",
            book_balance_as_of_period_end="5000",
        ),
    )
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="statement_balance_attachment",
                source="fixture",
                statement_end_date=date(2025, 12, 31),
                amount="5000",
                meta={"account_ref": "B1"},
            )
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, evidence=evidence, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.FAIL
    assert res.severity == Severity.HIGH
    assert "Checking" in res.summary


def test_bank_reconciled_needs_review_when_missing_statement_balance(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {
        "BS-BANK-RECONCILED-THROUGH-PERIOD-END": {
            "expected_accounts": ["B1"],
        }
    }
    bs = make_balance_sheet(
        accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "5000"}]
    )
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_ending_balance=None,
            book_balance_as_of_statement_end="5000",
            book_balance_as_of_period_end="5000",
        ),
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
