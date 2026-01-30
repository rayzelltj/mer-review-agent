import json
from pathlib import Path

from adapters.qbo.profit_and_loss import profit_and_loss_snapshot_from_report


FIXTURE_DIR = Path(__file__).parents[4] / "BlackBird Fabrics 2025-12-31"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_profit_and_loss_blackbird_parses_revenue_and_dates():
    report = _load("profit_and_loss.json")
    snapshot = profit_and_loss_snapshot_from_report(report)
    assert snapshot.period_start.isoformat() == "2025-08-01"
    assert snapshot.period_end.isoformat() == "2025-12-31"
    assert snapshot.currency == "CAD"
    assert str(snapshot.totals["revenue"]) == "1576382.88"
