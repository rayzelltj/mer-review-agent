from pathlib import Path

from common.rules_engine.models import RuleStatus
from scripts.run_balance_review import (
    build_fixture_review_inputs,
    run_balance_review_from_inputs,
)


FIXTURES = (
    Path(__file__).parent
    / "fixtures"
    / "blackbird_fabrics"
    / "2025-12-31"
)


def test_fixture_bundle_contains_required_evidence():
    inputs = build_fixture_review_inputs(FIXTURES)
    evidence_types = {item.evidence_type for item in inputs.evidence.items}
    expected = {
        "ap_aging_summary_total",
        "ap_aging_detail_total",
        "ar_aging_summary_total",
        "ar_aging_detail_total",
        "tax_agencies",
        "tax_returns",
        "tax_payments",
        "intercompany_balance_sheet",
    }
    assert expected.issubset(evidence_types)


def test_balance_review_rules_run_deterministically():
    inputs = build_fixture_review_inputs(FIXTURES)
    report = run_balance_review_from_inputs(inputs)
    by_id = {result.rule_id: result.status for result in report.results}
    assert by_id["BS-AP-SUBLEDGER-RECONCILES"] == RuleStatus.FAIL
    assert by_id["BS-AR-SUBLEDGER-RECONCILES"] == RuleStatus.PASS
    assert by_id["BS-TAX-FILINGS-UP-TO-DATE"] == RuleStatus.PASS
