import json
from pathlib import Path

from adapters.qbo.accounts import account_type_map_from_accounts_payload
from adapters.qbo.balance_sheet import balance_sheet_snapshot_from_report


FIXTURE_DIR = Path(__file__).parents[4] / "BlackBird Fabrics 2025-12-31"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_balance_sheet_blackbird_includes_total_lines_when_enabled():
    report = _load("balance_sheet.json")
    snapshot = balance_sheet_snapshot_from_report(report, include_summary_totals=True)
    refs = {a.account_ref for a in snapshot.accounts}
    assert "report::Total Accounts Payable (A/P)" in refs
    assert "report::Total Accounts Receivable (A/R)" in refs

    ap_total = next(a for a in snapshot.accounts if a.account_ref == "report::Total Accounts Payable (A/P)")
    ar_total = next(a for a in snapshot.accounts if a.account_ref == "report::Total Accounts Receivable (A/R)")
    assert str(ap_total.balance) == "-209.01"
    assert str(ar_total.balance) == "0.00"


def test_balance_sheet_blackbird_enriches_types_from_accounts_list():
    report = _load("balance_sheet.json")
    accounts_payload = _load("accounts.json")
    type_map = account_type_map_from_accounts_payload(accounts_payload)
    snapshot = balance_sheet_snapshot_from_report(report, account_types=type_map)

    ap = next(a for a in snapshot.accounts if a.account_ref == "65")
    assert ap.type == "Accounts Payable"
    assert ap.subtype == "AccountsPayable"
