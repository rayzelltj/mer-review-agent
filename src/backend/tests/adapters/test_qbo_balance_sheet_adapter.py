import json
from pathlib import Path

from adapters.qbo.accounts import account_type_map_from_accounts_payload
from adapters.qbo.balance_sheet import balance_sheet_snapshot_from_report


FIXTURES = Path(__file__).parent / "fixtures" / "qbo"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_balance_sheet_adapter_parses_accounts_and_header_date():
    report = _load("balance_sheet_report_sample.json")
    snapshot = balance_sheet_snapshot_from_report(report)
    assert snapshot.as_of_date.isoformat() == "2016-10-31"
    assert snapshot.currency == "USD"

    # Only rows with stable account ids are included by default.
    refs = {a.account_ref for a in snapshot.accounts}
    assert refs == {"35", "4"}

    checking = next(a for a in snapshot.accounts if a.account_ref == "35")
    assert checking.name == "Checking"
    assert str(checking.balance) == "1350.55"  # comma in input is handled


def test_balance_sheet_adapter_can_include_rows_without_id_when_enabled():
    report = _load("balance_sheet_report_sample.json")
    snapshot = balance_sheet_snapshot_from_report(report, include_rows_without_id=True)
    refs = {a.account_ref for a in snapshot.accounts}
    assert "report::Net Income" in refs


def test_balance_sheet_adapter_enriches_type_subtype_from_accounts_payload():
    report = _load("balance_sheet_report_sample.json")
    accounts_payload = _load("accounts_query_sample.json")
    type_map = account_type_map_from_accounts_payload(accounts_payload)
    snapshot = balance_sheet_snapshot_from_report(report, account_types=type_map)

    checking = next(a for a in snapshot.accounts if a.account_ref == "35")
    assert checking.type == "Bank"
    assert checking.subtype == "Checking"
