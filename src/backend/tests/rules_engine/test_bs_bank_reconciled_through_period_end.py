from datetime import date
from decimal import Decimal

from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus, Severity
from common.rules_engine.rules.bs_bank_reconciled_through_period_end import (
    BS_BANK_RECONCILED_THROUGH_PERIOD_END,
)


RULE_ID = "BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END"


def _coa_item(accounts: list[dict]) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="qbo_chart_of_accounts_bank_cc_active",
        source="fixture",
        as_of_date=date(2025, 12, 31),
        meta={"accounts": accounts},
    )


def _trial_item(balances_by_account_ref: dict[str, str]) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="qbo_trial_balance_register_balance",
        source="fixture",
        as_of_date=date(2025, 12, 31),
        meta={"balances_by_account_ref": balances_by_account_ref},
    )


def _tx_item(account_ref: str, s1: str, s2: str, clear_col: bool = True) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="qbo_transaction_list_unreconciled",
        source="fixture",
        as_of_date=date(2025, 12, 31),
        meta={
            "account_ref": account_ref,
            "account_id": account_ref,
            "sum_not_reconciled_as_of_period_end": s1,
            "sum_not_reconciled_between_period_end_and_statement_end": s2,
            "clear_status_column_found": clear_col,
            "parsed_rows": 12,
            "ignored_rows": 0,
        },
    )


def _statement_item(account_ref: str, amount: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="statement_balance_attachment",
        source="fixture",
        statement_end_date=date(2025, 12, 31),
        amount=amount,
        meta={"account_ref": account_ref},
    )


def test_bank_cc_reconciled_pass_when_expected_equals_s1(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    }
                ]
            ),
            _trial_item({"67": "13261.63"}),
            _statement_item("67", "13000.00"),
            _tx_item("67", "261.63", "0"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    assert res.status == RuleStatus.PASS
    assert res.severity == Severity.INFO
    assert res.details[0].values["account_active"] is True
    assert res.details[0].values["account_type"] == "Bank"


def test_bank_cc_reconciled_pass_when_expected_minus_s1_equals_s2(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    }
                ]
            ),
            _trial_item({"67": "13261.63"}),
            _statement_item("67", "13000.00"),
            _tx_item("67", "200.00", "61.63"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    assert res.status == RuleStatus.PASS
    assert res.details[0].values["pass_if_expected_minus_s1_equals_s2"] is True


def test_bank_cc_reconciled_warn_when_equation_mismatch(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    }
                ]
            ),
            _trial_item({"67": "13261.63"}),
            _statement_item("67", "13000.00"),
            _tx_item("67", "100.00", "50.00"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    assert res.status == RuleStatus.WARN
    assert res.severity == Severity.LOW


def test_bank_cc_reconciled_needs_review_when_missing_transaction_data(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    }
                ]
            ),
            _trial_item({"67": "13261.63"}),
            _statement_item("67", "13000.00"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW
    assert "transaction_list_s1_s2" in res.details[0].values["missing_fields"]


def test_bank_cc_reconciled_uses_active_bank_and_credit_card_scope_only(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
            {"account_ref": "132", "name": "RBC - VISA 1752/1760", "type": "Credit Card", "balance": "-54715.04"},
            {"account_ref": "999", "name": "Inactive Card", "type": "Credit Card", "balance": "0"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    },
                    {
                        "account_ref": "132",
                        "account_id": "132",
                        "account_name": "RBC - VISA 1752/1760",
                        "account_type": "Credit Card",
                        "active": True,
                    },
                    {
                        "account_ref": "999",
                        "account_id": "999",
                        "account_name": "Inactive Card",
                        "account_type": "Credit Card",
                        "active": False,
                    },
                ]
            ),
            _trial_item({"67": "13261.63", "132": "-54715.04"}),
            _statement_item("67", "13000.00"),
            _statement_item("132", "54715.04"),
            _tx_item("67", "261.63", "0"),
            _tx_item("132", "0.00", "0"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    assert res.status == RuleStatus.PASS
    evaluated = {d.key for d in res.details}
    assert evaluated == {"67", "132"}


def test_bank_cc_reconciled_needs_review_when_no_coa_and_fallback_disabled(make_balance_sheet, make_ctx):
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "", "balance": "13261.63"},
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(
            balance_sheet=bs,
            evidence=EvidenceBundle(items=[]),
            client_rules={RULE_ID: {"allow_fallback_name_heuristics_when_coa_missing": False}},
        )
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_bank_cc_reconciled_warn_when_register_does_not_match_bs_line(make_balance_sheet, make_ctx):
    """
    Rule 2 sub-check: when the trial-balance register balance differs from the
    balance-sheet line by more than $0.02, the overall result is WARN even if the
    reconciliation equation itself passes.
    """
    # BS shows 13261.63, TB register shows 13000.00 → mismatch > 0.02
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    }
                ]
            ),
            # TB register = 13000.00 (different from BS 13261.63)
            _trial_item({"67": "13000.00"}),
            # Statement = 12738.37 → expected_outstanding = 13000.00 - 12738.37 = 261.63
            _statement_item("67", "12738.37"),
            # S1 = 261.63 → equation PASS
            _tx_item("67", "261.63", "0"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    # Equation passes but Rule 2 sub-check fires → overall WARN
    assert res.status == RuleStatus.WARN
    detail_vals = res.details[0].values
    assert detail_vals["register_matches_bs_line"] is False
    assert detail_vals["sub_check_register_vs_bs"] == "WARN"
    assert detail_vals["equation_result"] == "PASS_BUT_REGISTER_VS_BS_MISMATCH"


def test_bank_cc_reconciled_pass_includes_bs_line_match_when_register_equals_bs(make_balance_sheet, make_ctx):
    """
    Rule 2 sub-check: when register == BS line (within $0.02) the sub-check passes
    and does not degrade the overall status.
    """
    bs = make_balance_sheet(
        accounts=[
            {"account_ref": "67", "name": "Paypal CAD Account", "type": "Bank", "balance": "13261.63"},
        ]
    )
    evidence = EvidenceBundle(
        items=[
            _coa_item(
                [
                    {
                        "account_ref": "67",
                        "account_id": "67",
                        "account_name": "Paypal CAD Account",
                        "account_type": "Bank",
                        "active": True,
                    }
                ]
            ),
            _trial_item({"67": "13261.63"}),
            _statement_item("67", "13000.00"),
            _tx_item("67", "261.63", "0"),
        ]
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={RULE_ID: {}})
    )
    assert res.status == RuleStatus.PASS
    detail_vals = res.details[0].values
    assert detail_vals["register_matches_bs_line"] is True
    assert detail_vals["sub_check_register_vs_bs"] == "PASS"
    assert detail_vals["bs_line_balance"] == "13261.63"
    assert detail_vals["bs_vs_register_diff"] == "0.00"
