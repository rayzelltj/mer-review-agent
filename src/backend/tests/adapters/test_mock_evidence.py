import json
from pathlib import Path

from adapters.mock_evidence import evidence_bundle_from_manifest, reconciliation_snapshot_from_report


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mock_evidence"
BLACKBIRD_FIXTURES = (
    Path(__file__).parents[1]
    / "rules_engine"
    / "fixtures"
    / "blackbird_fabrics"
    / "2025-11-30"
)


def test_evidence_bundle_from_manifest_parses_items():
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    bundle = evidence_bundle_from_manifest(manifest)
    assert len(bundle.items) == 3
    types = {item.evidence_type for item in bundle.items}
    assert "statement_balance_attachment" in types
    assert "petty_cash_support" in types


def test_reconciliation_snapshot_from_report_maps_balances():
    report = json.loads((BLACKBIRD_FIXTURES / "reconciliation_report_paypal_aud.json").read_text("utf-8"))
    snap = reconciliation_snapshot_from_report(report, account_ref="name::Paypal AUD Account")
    assert snap.account_ref == "name::Paypal AUD Account"
    assert str(snap.statement_ending_balance) == "4580.25"
    assert str(snap.book_balance_as_of_statement_end) == "4580.25"
    assert snap.book_balance_as_of_period_end is not None
