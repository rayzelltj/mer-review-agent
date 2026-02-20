from datetime import date
from pathlib import Path

from common.rules_engine.config import ClientRulesConfig
from common.rules_engine.context import RuleContext
from common.rules_engine.models import EvidenceBundle, EvidenceItem, RuleStatus
from common.rules_engine.rules.bs_bank_reconciled_through_period_end import (
    BS_BANK_RECONCILED_THROUGH_PERIOD_END,
)
from scripts.run_balance_review import build_fixture_review_inputs


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "blackbird_fabrics" / "2025-12-31"
RULE_ID = "BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END"


def test_blackbird_bank_cc_rule_needs_review_without_transaction_lists():
    inputs = build_fixture_review_inputs(FIXTURE_DIR)
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=inputs.period_end,
            balance_sheet=inputs.balance_sheet,
            prior_balance_sheets=inputs.prior_balance_sheets,
            profit_and_loss=inputs.profit_and_loss,
            evidence=inputs.evidence,
            reconciliations=inputs.reconciliations,
            client_config=ClientRulesConfig(rules={RULE_ID: {}}),
        )
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_blackbird_bank_cc_rule_pass_for_paypal_aud_when_s1_s2_provided():
    inputs = build_fixture_review_inputs(FIXTURE_DIR)
    augmented_evidence = EvidenceBundle(
        items=list(inputs.evidence.items)
        + [
            EvidenceItem(
                evidence_type="qbo_transaction_list_unreconciled",
                source="fixture",
                as_of_date=date(2025, 12, 31),
                meta={
                    "account_ref": "86",
                    "account_id": "86",
                    "sum_not_reconciled_as_of_period_end": "0",
                    "sum_not_reconciled_between_period_end_and_statement_end": "0",
                    "clear_status_column_found": True,
                    "parsed_rows": 10,
                    "ignored_rows": 0,
                },
            )
        ],
    )
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=inputs.period_end,
            balance_sheet=inputs.balance_sheet,
            prior_balance_sheets=inputs.prior_balance_sheets,
            profit_and_loss=inputs.profit_and_loss,
            evidence=augmented_evidence,
            reconciliations=inputs.reconciliations,
            client_config=ClientRulesConfig(
                rules={
                    RULE_ID: {
                        "expected_accounts": ["86"],
                    }
                }
            ),
        )
    )
    assert res.status == RuleStatus.PASS


def test_blackbird_bank_cc_rule_pass_for_paypal_cad_with_clr_column_fixtures():
    """
    Account 67 (Paypal CAD): all transactions Clr=R → S1=0, S2=0.
    TB register = 13261.63, statement ending = 13261.63 → expected_outstanding = 0.00 = S1 → PASS.
    Rule 2 sub-check: BS line = 13261.63 = register → register_matches_bs_line = True.
    """
    inputs = build_fixture_review_inputs(FIXTURE_DIR)
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=inputs.period_end,
            balance_sheet=inputs.balance_sheet,
            prior_balance_sheets=inputs.prior_balance_sheets,
            profit_and_loss=inputs.profit_and_loss,
            evidence=inputs.evidence,
            reconciliations=inputs.reconciliations,
            client_config=ClientRulesConfig(
                rules={
                    RULE_ID: {
                        "expected_accounts": ["67"],
                    }
                }
            ),
        )
    )
    assert res.status == RuleStatus.PASS
    detail_vals = res.details[0].values
    assert detail_vals["clear_status_column_found"] is True
    assert detail_vals["s1_not_reconciled_as_of_period_end"] == "0"
    assert detail_vals["s2_not_reconciled_between_period_end_and_statement_end"] == "0"
    assert detail_vals["register_matches_bs_line"] is True
    assert detail_vals["sub_check_register_vs_bs"] == "PASS"


def test_blackbird_bank_cc_rule_pass_for_rbc_visa_with_clr_column_fixtures():
    """
    Account 132 (RBC VISA 1752/1760): 28 rows Clr=R, 2 rows Clr=blank (Dec 29 and Dec 30).
    TB register net = -54715.04 → normalised = 54715.04.
    Statement ending balance = 31435.80 (period Nov 28 – Dec 29, 2025).
    Expected outstanding = 54715.04 - 31435.80 = 23279.24.
    S1 = 23250.24 + 29.00 = 23279.24 → PASS.
    Rule 2 sub-check: BS line = 54715.04 = register → register_matches_bs_line = True.
    """
    inputs = build_fixture_review_inputs(FIXTURE_DIR)
    res = BS_BANK_RECONCILED_THROUGH_PERIOD_END().evaluate(
        RuleContext(
            period_end=inputs.period_end,
            balance_sheet=inputs.balance_sheet,
            prior_balance_sheets=inputs.prior_balance_sheets,
            profit_and_loss=inputs.profit_and_loss,
            evidence=inputs.evidence,
            reconciliations=inputs.reconciliations,
            client_config=ClientRulesConfig(
                rules={
                    RULE_ID: {
                        "expected_accounts": ["132"],
                    }
                }
            ),
        )
    )
    assert res.status == RuleStatus.PASS
    detail_vals = res.details[0].values
    assert detail_vals["clear_status_column_found"] is True
    assert detail_vals["s1_not_reconciled_as_of_period_end"] == "23279.24"
    assert detail_vals["s2_not_reconciled_between_period_end_and_statement_end"] == "0"
    assert detail_vals["pass_if_expected_equals_s1"] is True
    assert detail_vals["register_matches_bs_line"] is True
    assert detail_vals["sub_check_register_vs_bs"] == "PASS"
