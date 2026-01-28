import json
from pathlib import Path

from adapters.qbo.profit_and_loss import profit_and_loss_snapshot_from_report


FIXTURES = Path(__file__).parent / "fixtures" / "qbo"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_profit_and_loss_adapter_parses_header_and_revenue():
    report = _load("profit_and_loss_report_sample.json")
    snapshot = profit_and_loss_snapshot_from_report(report)
    assert snapshot.period_start.isoformat() == "2015-06-01"
    assert snapshot.period_end.isoformat() == "2015-06-30"
    assert snapshot.currency == "USD"
    assert snapshot.totals.get("revenue") == snapshot.totals["revenue"]
    assert str(snapshot.totals["revenue"]) == "325.00"


def test_profit_and_loss_adapter_fallbacks_to_label_when_group_missing():
    report = _load("profit_and_loss_report_sample.json")
    # Remove the group to force fallback by label "Total Income"
    report["Rows"]["Row"][0].pop("group", None)
    snapshot = profit_and_loss_snapshot_from_report(report)
    assert str(snapshot.totals["revenue"]) == "325.00"

