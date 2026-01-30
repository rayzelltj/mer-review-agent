import json
from pathlib import Path

from adapters.qbo.accounts import account_type_map_from_accounts_payload


FIXTURE_DIR = Path(__file__).parents[4] / "BlackBird Fabrics 2025-12-31"


def _load(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_accounts_adapter_parses_list_payload():
    payload = _load("accounts.json")
    mapping = account_type_map_from_accounts_payload(payload)
    assert mapping["65"].account_type == "Accounts Payable"
    assert mapping["65"].account_subtype == "AccountsPayable"
