import json
from pathlib import Path

from adapters.qbo.accounts import account_type_map_from_accounts_payload


FIXTURES = Path(__file__).parent / "fixtures" / "qbo"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_accounts_adapter_parses_query_response():
    payload = _load("accounts_query_sample.json")
    mapping = account_type_map_from_accounts_payload(payload)
    assert mapping["35"].account_type == "Bank"
    assert mapping["35"].account_subtype == "Checking"
    assert mapping["4"].account_type == "Other Current Asset"
    assert mapping["4"].account_subtype == "UndepositedFunds"


def test_accounts_adapter_handles_single_account_shape():
    payload = {
        "Account": {
            "Id": "92",
            "AccountType": "Accounts Receivable",
            "AccountSubType": "AccountsReceivable",
        }
    }
    mapping = account_type_map_from_accounts_payload(payload)
    assert mapping["92"].account_type == "Accounts Receivable"
    assert mapping["92"].account_subtype == "AccountsReceivable"

