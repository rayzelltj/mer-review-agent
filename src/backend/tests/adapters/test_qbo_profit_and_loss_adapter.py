import json
from pathlib import Path

from adapters.qbo.profit_and_loss import (
    QBOProfitAndLossAdapterError,
    expense_month_over_month_from_report,
    profit_and_loss_snapshot_from_report,
)


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


def test_profit_and_loss_adapter_uses_mer_month_when_summarized_by_month():
    report = _load("profit_and_loss_report_by_month_sample.json")
    snapshot = profit_and_loss_snapshot_from_report(report, summarize_by_month=True)
    assert snapshot.period_end.isoformat() == "2025-11-30"
    assert str(snapshot.totals["revenue"]) == "400.00"


def test_profit_and_loss_adapter_errors_when_mer_month_column_missing():
    report = _load("profit_and_loss_report_by_month_sample.json")
    report["Header"]["EndPeriod"] = "2025-12-31"
    try:
        profit_and_loss_snapshot_from_report(report, summarize_by_month=True)
    except QBOProfitAndLossAdapterError as exc:
        assert "Monthly column" in str(exc)
        return
    raise AssertionError("Expected QBOProfitAndLossAdapterError for missing month column.")


def test_expense_month_over_month_extracts_line_variances():
    report = {
        "Header": {
            "ReportName": "ProfitAndLoss",
            "StartPeriod": "2025-11-01",
            "EndPeriod": "2025-12-31",
            "Currency": "USD",
            "SummarizeColumnsBy": "Month",
        },
        "Columns": {
            "Column": [
                {"ColTitle": "", "MetaData": [{"Name": "ColKey", "Value": "account"}]},
                {"ColTitle": "Nov. 2025"},
                {"ColTitle": "Dec. 2025"},
                {"ColTitle": "Total", "MetaData": [{"Name": "ColKey", "Value": "total"}]},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "group": "Expenses",
                    "type": "Section",
                    "Rows": {
                        "Row": [
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": "Advertising"},
                                    {"value": "100.00"},
                                    {"value": "150.00"},
                                    {"value": "250.00"},
                                ],
                            },
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": "Office supplies"},
                                    {"value": "200.00"},
                                    {"value": "180.00"},
                                    {"value": "380.00"},
                                ],
                            },
                        ]
                    },
                }
            ]
        },
    }

    out = expense_month_over_month_from_report(report)
    by_name = {row["name"]: row for row in out["lines"]}
    assert out["current_period_end"] == "2025-12-31"
    assert out["prior_period_end"] == "2025-11-30"
    assert by_name["Advertising"]["delta_amount"] == "50.00"
    assert by_name["Advertising"]["abs_pct_change"] == "0.5"
    assert by_name["Office supplies"]["delta_amount"] == "-20.00"
