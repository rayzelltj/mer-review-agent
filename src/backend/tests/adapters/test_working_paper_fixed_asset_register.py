from datetime import date
from decimal import Decimal

from adapters.working_papers.fixed_asset_register import (
    depreciation_schedule_to_evidence,
    fixed_asset_register_csv_to_evidence,
)


def test_fixed_asset_register_csv_extracts_closing_balance(tmp_path):
    fixture = tmp_path / "Fixed Asset Register - Equipment.csv"
    fixture.write_text("Closing Balance,2650.41\n", encoding="utf-8")
    evidence = fixed_asset_register_csv_to_evidence(fixture, period_end=date(2025, 12, 31))

    assert evidence.evidence_type == "fixed_asset_register_balance"
    assert evidence.as_of_date == date(2025, 12, 31)
    assert evidence.amount == Decimal("2650.41")
    assert evidence.meta["asset_class"] == "Equipment"
    assert evidence.meta["account_name_match"] == "Equipment"


def test_depreciation_schedule_extracts_period_end_items(tmp_path):
    fixture = tmp_path / "Fixed Asset_Depreciation Schedule 2026.csv"
    fixture.write_text(
        "\n".join(
            [
                "Asset Class,Purpose,31 Dec 2025",
                "Computer Equipment,Opening Balance,",
                ",Closing Balance as per register,2064.60",
                "Website,Opening Balance,",
                ",Closing Balance as per register,12685.80",
                "",
            ]
        ),
        encoding="utf-8",
    )
    evidence = depreciation_schedule_to_evidence(fixture, period_end=date(2025, 12, 31))

    assert evidence.evidence_type == "fixed_asset_register_balance"
    assert evidence.as_of_date == date(2025, 12, 31)
    assert evidence.meta["month_label"] == "31 Dec 2025"
    items = evidence.meta["items"]
    assert isinstance(items, list)
    assert any(item["account_name_match"] == "Website" and item["balance"] == "12685.80" for item in items)
    assert any(item["account_name_match"] == "Computer Equipment" and item["balance"] == "2064.60" for item in items)
