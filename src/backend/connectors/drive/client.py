from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from common.telemetry import traced_phase

from .auth import ensure_access_token_valid, refresh_access_token
from .config import DriveConfig

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_GOOGLE_DOC_MIME_PREFIX = "application/vnd.google-apps."
_DEFAULT_EXPORT_MIME_BY_TYPE = {
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}


class DriveHttpError(RuntimeError):
    def __init__(self, status: int, message: str, body: str | None = None):
        super().__init__(f"Drive HTTP {status}: {message}")
        self.status = status
        self.body = body


def list_files(
    config: DriveConfig,
    *,
    folder_id: str,
    query: str | None = None,
    fields: str | None = None,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """List files in a Drive folder with basic pagination support."""
    normalized_folder = str(folder_id or "").strip()
    if not normalized_folder:
        raise ValueError("folder_id is required")

    cfg = ensure_access_token_valid(config)
    all_files: list[dict[str, Any]] = []
    page_token: str | None = None
    normalized_fields = (
        fields
        or "nextPageToken,files(id,name,mimeType,modifiedTime,size,parents,webViewLink,driveId)"
    )
    safe_page_size = max(1, min(page_size, 1000))

    while True:
        q_parts = [f"'{normalized_folder}' in parents", "trashed=false"]
        normalized_query = str(query or "").strip()
        if normalized_query:
            q_parts.append(f"({normalized_query})")

        params = {
            "q": " and ".join(q_parts),
            "fields": normalized_fields,
            "pageSize": str(safe_page_size),
            "supportsAllDrives": _bool_param(cfg.supports_all_drives),
            "includeItemsFromAllDrives": _bool_param(cfg.include_items_from_all_drives),
        }
        if page_token:
            params["pageToken"] = page_token

        payload = _drive_get_json(cfg, "/files", params=params)
        files = payload.get("files")
        if isinstance(files, list):
            all_files.extend(item for item in files if isinstance(item, dict))

        next_token = str(payload.get("nextPageToken") or "").strip()
        if not next_token:
            break
        page_token = next_token

    return all_files


def get_file_metadata(
    config: DriveConfig,
    *,
    file_id: str,
    fields: str | None = None,
) -> dict[str, Any]:
    normalized_file_id = str(file_id or "").strip()
    if not normalized_file_id:
        raise ValueError("file_id is required")
    cfg = ensure_access_token_valid(config)
    params = {
        "fields": fields
        or "id,name,mimeType,size,modifiedTime,webViewLink,parents,driveId",
        "supportsAllDrives": _bool_param(cfg.supports_all_drives),
    }
    return _drive_get_json(cfg, f"/files/{normalized_file_id}", params=params)


def download_file(
    config: DriveConfig,
    *,
    file_id: str,
    destination_path: str,
    export_mime_type: str | None = None,
) -> str:
    """Download file bytes to destination_path and return the written path."""
    content = download_file_bytes(
        config,
        file_id=file_id,
        export_mime_type=export_mime_type,
    )
    out_path = Path(destination_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    return str(out_path)


def download_file_bytes(
    config: DriveConfig,
    *,
    file_id: str,
    export_mime_type: str | None = None,
) -> bytes:
    normalized_file_id = str(file_id or "").strip()
    if not normalized_file_id:
        raise ValueError("file_id is required")

    cfg = ensure_access_token_valid(config)
    metadata = get_file_metadata(cfg, file_id=normalized_file_id)
    mime_type = str(metadata.get("mimeType") or "").strip()

    if mime_type.startswith(_GOOGLE_DOC_MIME_PREFIX):
        chosen_export_mime = (
            str(export_mime_type or "").strip()
            or _DEFAULT_EXPORT_MIME_BY_TYPE.get(mime_type, "text/plain")
        )
        return _drive_get_bytes(
            cfg,
            f"/files/{normalized_file_id}/export",
            params={
                "mimeType": chosen_export_mime,
                "supportsAllDrives": _bool_param(cfg.supports_all_drives),
            },
        )

    return _drive_get_bytes(
        cfg,
        f"/files/{normalized_file_id}",
        params={
            "alt": "media",
            "supportsAllDrives": _bool_param(cfg.supports_all_drives),
        },
    )


def download_file_json(
    config: DriveConfig,
    *,
    file_id: str,
) -> dict[str, Any]:
    payload = download_file_bytes(config, file_id=file_id, export_mime_type="application/json")
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Drive file '{file_id}' does not contain valid JSON.") from exc


def _drive_get_json(
    config: DriveConfig,
    path: str,
    *,
    params: dict[str, str] | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    body = _drive_get_bytes(config, path, params=params, timeout_seconds=timeout_seconds)
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise DriveHttpError(0, "Invalid JSON response from Google Drive API.") from exc
    if not isinstance(payload, dict):
        return {"data": payload}
    return payload


def _drive_get_bytes(
    config: DriveConfig,
    path: str,
    *,
    params: dict[str, str] | None = None,
    timeout_seconds: int = 30,
) -> bytes:
    cfg = config
    refreshed = False

    while True:
        url = _build_url(path, params=params)
        req = Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {cfg.access_token}")
        req.add_header("Accept", "application/json")

        try:
            with traced_phase(
                "dependency.drive.http_get",
                attributes={"http.url": url, "http.method": "GET"},
            ):
                with urlopen(req, timeout=timeout_seconds) as response:
                    return response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else None
            if exc.code == 401 and not refreshed:
                cfg = refresh_access_token(cfg)
                refreshed = True
                continue
            raise DriveHttpError(exc.code, exc.reason, body) from exc
        except URLError as exc:
            raise DriveHttpError(0, str(exc)) from exc


def _build_url(path: str, *, params: dict[str, str] | None = None) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    base = f"{DRIVE_API_BASE}{normalized_path}"
    if not params:
        return base
    query = urlencode(params)
    return f"{base}?{query}"


def _bool_param(value: bool) -> str:
    return "true" if value else "false"
