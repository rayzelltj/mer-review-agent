import json

import pytest

from connectors.drive.config import build_drive_config


def test_build_drive_config_uses_client_overrides(tmp_path, monkeypatch):
    clients_path = tmp_path / "clients.json"
    clients_path.write_text(
        json.dumps(
            {
                "clients": {
                    "Example Client Inc.": {
                        "realm_id": "999999999999999",
                        "drive": {
                            "root_folder_id": "folder-001",
                            "evidence_manifest_file_id": "manifest-001",
                            "include_items_from_all_drives": False,
                            "supports_all_drives": True,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("QBO_CLIENT_STORE", "file")
    monkeypatch.setenv("CLIENT_CONFIG_PATH", str(clients_path))
    monkeypatch.setenv("DRIVE_CLIENT_ID", "drive-client-id")
    monkeypatch.setenv("DRIVE_CLIENT_SECRET", "drive-client-secret")
    monkeypatch.setenv("DRIVE_REFRESH_TOKEN", "drive-refresh-token")
    monkeypatch.setenv("DRIVE_ACCESS_TOKEN", "drive-access-token")
    monkeypatch.setenv("DRIVE_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")

    cfg = build_drive_config(client_id="example")

    assert cfg.client_record_id == "Example Client Inc."
    assert cfg.root_folder_id == "folder-001"
    assert cfg.evidence_manifest_file_id == "manifest-001"
    assert cfg.include_items_from_all_drives is False
    assert cfg.supports_all_drives is True


def test_build_drive_config_raises_without_required_credentials(monkeypatch):
    monkeypatch.setenv("QBO_CLIENT_STORE", "file")
    monkeypatch.delenv("DRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("DRIVE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("DRIVE_REFRESH_TOKEN", raising=False)

    with pytest.raises(ValueError):
        build_drive_config()
