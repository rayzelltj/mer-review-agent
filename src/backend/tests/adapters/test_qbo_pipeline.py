import json
from pathlib import Path

from adapters.qbo.pipeline import build_qbo_snapshots


FIXTURES = Path(__file__).parent / "fixtures" / "qbo"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_qbo_pipeline_builds_snapshots_with_type_enrichment():
    bs_report = _load("balance_sheet_report_sample.json")
    pnl_report = _load("profit_and_loss_report_sample.json")
    accounts = _load("accounts_query_sample.json")

    out = build_qbo_snapshots(
        balance_sheet_report=bs_report,
        profit_and_loss_report=pnl_report,
        accounts_payload=accounts,
        realm_id="999",
    )

    assert out.balance_sheet.as_of_date.isoformat() == "2016-10-31"
    assert out.profit_and_loss is not None
    assert out.profit_and_loss.totals.get("revenue") is not None

    checking = next(a for a in out.balance_sheet.accounts if a.account_ref.endswith("::35"))
    assert checking.type == "Bank"
    assert checking.subtype == "Checking"

