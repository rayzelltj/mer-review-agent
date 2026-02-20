from datetime import date

from adapters.qbo.fixed_assets import (
    active_fixed_asset_accounts_from_accounts_payload,
    fixed_asset_ledger_transactions_from_report,
)


def test_active_fixed_asset_accounts_filters_and_formats_refs():
    payload = {
        "QueryResponse": {
            "Account": [
                {"Id": "10", "Name": "Computer Equipment", "AccountType": "Fixed Asset", "Active": True},
                {"Id": "11", "Name": "Cash", "AccountType": "Bank", "Active": True},
                {"Id": "12", "Name": "Leasehold", "AccountType": "Fixed Asset", "Active": False},
            ]
        }
    }
    rows = active_fixed_asset_accounts_from_accounts_payload(payload, realm_id="999", active_only=True)
    assert len(rows) == 1
    assert rows[0]["account_id"] == "10"
    assert rows[0]["account_ref"] == "qbo::999::10"


def test_fixed_asset_ledger_transactions_from_report_parses_month_window():
    report = {
        "Header": {"StartPeriod": "2025-12-01", "EndPeriod": "2025-12-31"},
        "Columns": {
            "Column": [
                {"ColTitle": "Account", "MetaData": [{"Name": "ColKey", "Value": "account"}]},
                {"ColTitle": "Date"},
                {"ColTitle": "Transaction Type"},
                {"ColTitle": "Description"},
                {"ColTitle": "Amount"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Data",
                    "ColData": [
                        {"id": "10", "value": "Computer Equipment"},
                        {"value": "2025-12-05"},
                        {"value": "Bill"},
                        {"value": "Laptop purchase"},
                        {"value": "1200.00"},
                    ],
                },
                {
                    "type": "Data",
                    "ColData": [
                        {"id": "10", "value": "Computer Equipment"},
                        {"value": "2025-12-20"},
                        {"value": "Journal"},
                        {"value": "Adjustment"},
                        {"value": "(50.00)"},
                    ],
                },
                {
                    "type": "Data",
                    "ColData": [
                        {"id": "11", "value": "Cash"},
                        {"value": "2025-12-10"},
                        {"value": "Bill"},
                        {"value": "Other account"},
                        {"value": "999.99"},
                    ],
                },
            ]
        },
    }

    summary = fixed_asset_ledger_transactions_from_report(
        {"payload": report, "extra": {"account_id": "10"}},
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 31),
    )

    assert summary["account_id"] == "10"
    assert summary["parsed_rows"] == 2
    assert len(summary["transactions"]) == 2
    assert summary["transactions"][0]["amount"] == "1200.00"
    assert summary["transactions"][1]["amount"] == "-50.00"
