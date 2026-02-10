import json
import os
from datetime import date
from pathlib import Path

import pytest

from pipelines.data_source import get_data_source


REQUIRED_ENV = [
    "QBO_CLIENT_ID",
    "QBO_CLIENT_SECRET",
    "QBO_ACCESS_TOKEN",
    "QBO_REFRESH_TOKEN",
    "QBO_TOKEN_EXPIRES_AT",
    "QBO_REALM_ID",
    "LIVE_CLIENT_ID",
    "LIVE_PERIOD_END",
]


def _default_client_config_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "clients.json"


def _load_client_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_balance_review_evidence_types_present():
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live env vars: {', '.join(missing)}")

    client_id = os.getenv("LIVE_CLIENT_ID", "").strip()
    period_end_raw = os.getenv("LIVE_PERIOD_END", "").strip()
    if not client_id or not period_end_raw:
        pytest.skip("LIVE_CLIENT_ID or LIVE_PERIOD_END missing.")

    config_override = os.getenv("CLIENT_CONFIG_PATH", "").strip()
    config_path = Path(config_override).expanduser() if config_override else _default_client_config_path()
    cfg = _load_client_config(config_path)
    client_cfg = (cfg.get("clients") or {}).get(client_id)
    if not client_cfg or not str(client_cfg.get("realm_id") or "").strip():
        pytest.skip("Client config missing or incomplete for live test.")
    if str(client_cfg.get("realm_id")).strip().upper() == "REPLACE_ME":
        pytest.skip("Client config uses placeholder realm_id.")

    source = get_data_source("live")
    inputs = source.build_review_inputs(
        client_id=client_id,
        period_end=date.fromisoformat(period_end_raw),
    )
    evidence_types = {item.evidence_type for item in inputs.evidence.items}
    expected = {
        "ap_aging_summary_total",
        "ap_aging_detail_total",
        "ar_aging_summary_total",
        "ar_aging_detail_total",
        "tax_agencies",
        "tax_returns",
        "tax_payments",
        "intercompany_balance_sheet",
    }
    assert expected.issubset(evidence_types)
