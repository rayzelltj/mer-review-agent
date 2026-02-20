import json
from datetime import date

from connectors.drive.config import DriveConfig
from pipelines import live_qbo


def test_load_drive_manifest_evidence_builds_evidence_items(monkeypatch):
    period_end = date(2026, 1, 31)
    manifest = {
        "evidence": [
            {
                "evidence_type": "loan_schedule_balance",
                "amount": "123.45",
                "as_of_date": "2026-01-31",
                "uri": "drive://loan_schedule.csv",
            }
        ]
    }
    cfg = DriveConfig(
        client_id="drive-client-id",
        client_secret="drive-client-secret",
        refresh_token="drive-refresh-token",
        access_token="drive-access-token",
        token_expires_at="2099-01-01T00:00:00+00:00",
        evidence_manifest_file_id="manifest-file-id",
        client_record_id="Example Client Inc.",
    )

    monkeypatch.setattr(live_qbo, "is_drive_evidence_enabled", lambda: True)
    monkeypatch.setattr(
        live_qbo,
        "build_drive_config",
        lambda client_id, user_principal_id=None: cfg,
    )
    monkeypatch.setattr(
        live_qbo,
        "download_file_bytes",
        lambda *_args, **_kwargs: json.dumps(manifest).encode("utf-8"),
    )

    payload, items = live_qbo._load_drive_manifest_evidence(
        client_id="Example Client Inc.",
        period_end=period_end,
        user_principal_id="test-user-id",
    )

    assert payload == manifest
    assert len(items) == 1
    assert items[0].evidence_type == "loan_schedule_balance"
    assert items[0].amount is not None
    assert str(items[0].amount) == "123.45"
    assert items[0].as_of_date == period_end


def test_load_drive_manifest_evidence_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(live_qbo, "is_drive_evidence_enabled", lambda: False)

    payload, items = live_qbo._load_drive_manifest_evidence(
        client_id="Example Client Inc.",
        period_end=date(2026, 1, 31),
        user_principal_id="test-user-id",
    )

    assert payload is None
    assert items == []
