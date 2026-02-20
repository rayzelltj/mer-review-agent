from unittest.mock import patch

from connectors.drive.client import download_file_bytes, list_files
from connectors.drive.config import DriveConfig


def _cfg() -> DriveConfig:
    return DriveConfig(
        client_id="drive-client-id",
        client_secret="drive-client-secret",
        refresh_token="drive-refresh-token",
        access_token="drive-access-token",
        token_expires_at="2099-01-01T00:00:00+00:00",
        root_folder_id="root-folder",
        evidence_manifest_file_id="manifest-file",
        include_items_from_all_drives=True,
        supports_all_drives=True,
        client_record_id="Example Client Inc.",
    )


def test_list_files_paginates():
    cfg = _cfg()
    captured_params: list[dict[str, str]] = []

    def _fake_drive_get_json(config, path, *, params=None, timeout_seconds=30):
        assert path == "/files"
        assert config == cfg
        captured_params.append(dict(params or {}))
        if len(captured_params) == 1:
            return {"files": [{"id": "f1"}], "nextPageToken": "token-2"}
        return {"files": [{"id": "f2"}]}

    with patch("connectors.drive.client.ensure_access_token_valid", return_value=cfg):
        with patch("connectors.drive.client._drive_get_json", _fake_drive_get_json):
            files = list_files(cfg, folder_id="folder-123", query="name contains 'schedule'")

    assert [file["id"] for file in files] == ["f1", "f2"]
    assert "'folder-123' in parents" in captured_params[0]["q"]
    assert "name contains 'schedule'" in captured_params[0]["q"]
    assert captured_params[1]["pageToken"] == "token-2"


def test_download_file_bytes_exports_google_spreadsheet_as_csv():
    cfg = _cfg()
    captured: dict[str, object] = {}

    def _fake_get_bytes(config, path, *, params=None, timeout_seconds=30):
        captured["config"] = config
        captured["path"] = path
        captured["params"] = dict(params or {})
        return b"csv-bytes"

    with patch("connectors.drive.client.ensure_access_token_valid", return_value=cfg):
        with patch(
            "connectors.drive.client.get_file_metadata",
            return_value={"id": "abc123", "mimeType": "application/vnd.google-apps.spreadsheet"},
        ):
            with patch("connectors.drive.client._drive_get_bytes", _fake_get_bytes):
                out = download_file_bytes(cfg, file_id="abc123")

    assert out == b"csv-bytes"
    assert captured["path"] == "/files/abc123/export"
    assert captured["params"]["mimeType"] == "text/csv"
