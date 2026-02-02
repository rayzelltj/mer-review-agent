import json
from pathlib import Path

from adapters.qbo.aging_reports import aging_report_to_evidence


FIXTURE_DIR = Path(__file__).parents[4] / "BlackBird Fabrics 2025-12-31"


def _load(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_ap_aging_summary_to_evidence():
    report = _load("aged_payables_summary.json")
    items = aging_report_to_evidence(report, report_type="ap", report_kind="summary")
    total = next(i for i in items if i.evidence_type == "ap_aging_summary_total")
    over = next(i for i in items if i.evidence_type == "ap_aging_summary_over_60")
    assert str(total.amount) == "52157.70"
    assert str(over.amount) == "-123.66"
    assert over.meta.get("items")
    assert over.meta["items"][0]["name"] == "Best Buy"


def test_ap_aging_detail_to_evidence():
    report = _load("aged_payables_detail.json")
    items = aging_report_to_evidence(report, report_type="ap", report_kind="detail")
    total = next(i for i in items if i.evidence_type == "ap_aging_detail_total")
    over = next(i for i in items if i.evidence_type == "ap_aging_detail_over_60")
    rows = next(i for i in items if i.evidence_type == "ap_aging_detail_rows")
    assert str(total.amount) == "52157.70"
    assert str(over.amount) == "-123.66"
    assert rows.meta.get("items")


def test_ar_aging_summary_to_evidence():
    report = _load("aged_receivables_summary.json")
    items = aging_report_to_evidence(report, report_type="ar", report_kind="summary")
    total = next(i for i in items if i.evidence_type == "ar_aging_summary_total")
    over = next(i for i in items if i.evidence_type == "ar_aging_summary_over_60")
    assert str(total.amount) == "0.00"
    assert str(over.amount) == "0"


def test_ar_aging_detail_to_evidence():
    report = _load("aged_receivables_detail.json")
    items = aging_report_to_evidence(report, report_type="ar", report_kind="detail")
    total = next(i for i in items if i.evidence_type == "ar_aging_detail_total")
    over = next(i for i in items if i.evidence_type == "ar_aging_detail_over_60")
    rows = next(i for i in items if i.evidence_type == "ar_aging_detail_rows")
    assert str(total.amount) == "0.00"
    assert str(over.amount) == "0"
    assert rows.meta.get("items") is not None
