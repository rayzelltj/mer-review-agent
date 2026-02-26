from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pipelines import live_qbo


class _NoopSnapshotStore:
    def save_json(self, **_kwargs):
        return None


def test_fetch_raw_data_coerces_iso_period_end_string(monkeypatch):
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        live_qbo.LiveQBODataSource,
        "_get_client_config",
        lambda self, client_id: live_qbo.ClientConfig(
            client_id=client_id,
            realm_id="1234567890",
            counterparties=(),
            refresh_token="refresh-token",
        ),
    )
    monkeypatch.setattr(
        live_qbo,
        "_config_for_realm",
        lambda *_args, **_kwargs: SimpleNamespace(
            realm_id="1234567890",
            base_url="https://quickbooks.example",
        ),
    )
    monkeypatch.setattr(
        live_qbo,
        "fetch_balance_sheet",
        lambda *_args, **_kwargs: {"Header": {}, "Rows": {"Row": []}},
    )
    monkeypatch.setattr(live_qbo, "_validate_report_payload", lambda *_args, **_kwargs: None)

    def _stop_after_type_check(period_end: date, months_back: int) -> date:
        observed["period_end_type"] = type(period_end)
        observed["period_end_value"] = period_end.isoformat()
        observed["months_back"] = months_back
        raise RuntimeError("stop-after-period-end-coercion")

    monkeypatch.setattr(live_qbo, "_month_end_months_ago", _stop_after_type_check)

    source = live_qbo.LiveQBODataSource(
        snapshot_store=_NoopSnapshotStore(),
        client_store_mode="cosmos",
        user_principal_id="user-1",
    )

    with pytest.raises(RuntimeError, match="stop-after-period-end-coercion"):
        source.fetch_raw_data(client_id="blackbird_fabrics", period_end="2026-01-31")

    assert observed["period_end_type"] is date
    assert observed["period_end_value"] == "2026-01-31"
    assert observed["months_back"] == 1


def test_fetch_raw_data_rejects_invalid_period_end_before_client_lookup(monkeypatch):
    calls = {"client_lookup": 0}

    def _counted_client_lookup(self, _client_id: str):
        calls["client_lookup"] += 1
        return None

    monkeypatch.setattr(live_qbo.LiveQBODataSource, "_get_client_config", _counted_client_lookup)

    source = live_qbo.LiveQBODataSource(
        snapshot_store=_NoopSnapshotStore(),
        client_store_mode="cosmos",
        user_principal_id="user-1",
    )

    with pytest.raises(ValueError, match="invalid period_end"):
        source.fetch_raw_data(client_id="blackbird_fabrics", period_end="2026-13-31")

    assert calls["client_lookup"] == 0


def test_build_review_inputs_coerces_period_end_string(monkeypatch):
    observed: dict[str, object] = {}
    source = live_qbo.LiveQBODataSource(
        snapshot_store=_NoopSnapshotStore(),
        client_store_mode="cosmos",
        user_principal_id="user-1",
    )

    def _fake_fetch_raw_data(*, client_id: str, period_end: date):
        observed["client_id"] = client_id
        observed["period_end_type"] = type(period_end)
        observed["period_end_value"] = period_end.isoformat()
        raise RuntimeError("stop-after-build-review-inputs")

    monkeypatch.setattr(source, "fetch_raw_data", _fake_fetch_raw_data)

    with pytest.raises(RuntimeError, match="stop-after-build-review-inputs"):
        source.build_review_inputs(client_id="blackbird_fabrics", period_end="2026-01-31")

    assert observed["client_id"] == "blackbird_fabrics"
    assert observed["period_end_type"] is date
    assert observed["period_end_value"] == "2026-01-31"
