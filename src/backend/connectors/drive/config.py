from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.client_id import load_client_aliases, resolve_client_id
from connectors.qbo.client_store import get_qbo_client_record, list_qbo_client_ids
from connectors.qbo.config import get_client_store_mode


@dataclass(frozen=True)
class DriveConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: str
    token_expires_at: str
    root_folder_id: str | None = None
    evidence_manifest_file_id: str | None = None
    include_items_from_all_drives: bool = True
    supports_all_drives: bool = True
    client_record_id: str | None = None
    user_principal_id: str | None = None


def get_drive_config(
    *,
    client_id: str | None = None,
    user_principal_id: str | None = None,
) -> DriveConfig:
    """Load Drive connector configuration from env + optional client-level overrides."""
    return build_drive_config(
        client_id=client_id,
        user_principal_id=user_principal_id,
    )


def build_drive_config(
    *,
    client_id: str | None = None,
    user_principal_id: str | None = None,
    root_folder_id: str | None = None,
    evidence_manifest_file_id: str | None = None,
) -> DriveConfig:
    normalized_user = str(user_principal_id or "").strip() or None
    resolved_client_id = _resolve_client_id(
        client_id,
        user_principal_id=normalized_user,
    )
    client_overrides = _load_client_drive_settings(
        resolved_client_id,
        user_principal_id=normalized_user,
    )

    client_id_value = _require_env("DRIVE_CLIENT_ID")
    client_secret_value = _require_env("DRIVE_CLIENT_SECRET")
    refresh_token_value = _resolve_value(
        "DRIVE_REFRESH_TOKEN",
        explicit=client_overrides.get("refresh_token"),
        allow_empty=False,
    )
    access_token_value = _resolve_value(
        "DRIVE_ACCESS_TOKEN",
        explicit=client_overrides.get("access_token"),
        allow_empty=True,
    )
    token_expires_at_value = _resolve_value(
        "DRIVE_TOKEN_EXPIRES_AT",
        explicit=client_overrides.get("token_expires_at"),
        allow_empty=True,
    )

    folder_id = _first_non_empty(
        root_folder_id,
        _as_str(client_overrides.get("root_folder_id")),
        os.getenv("DRIVE_ROOT_FOLDER_ID", "").strip(),
    )
    manifest_file_id = _first_non_empty(
        evidence_manifest_file_id,
        _as_str(client_overrides.get("evidence_manifest_file_id")),
        os.getenv("DRIVE_EVIDENCE_MANIFEST_FILE_ID", "").strip(),
    )

    include_items_from_all_drives = _as_bool(
        client_overrides.get("include_items_from_all_drives"),
        default=True,
    )
    supports_all_drives = _as_bool(
        client_overrides.get("supports_all_drives"),
        default=True,
    )

    return DriveConfig(
        client_id=client_id_value,
        client_secret=client_secret_value,
        refresh_token=refresh_token_value,
        access_token=access_token_value,
        token_expires_at=token_expires_at_value,
        root_folder_id=folder_id,
        evidence_manifest_file_id=manifest_file_id,
        include_items_from_all_drives=include_items_from_all_drives,
        supports_all_drives=supports_all_drives,
        client_record_id=resolved_client_id,
        user_principal_id=normalized_user,
    )


def get_drive_manifest_file_id(
    client_id: str | None,
    *,
    user_principal_id: str | None = None,
) -> str | None:
    try:
        cfg = build_drive_config(
            client_id=client_id,
            user_principal_id=user_principal_id,
        )
    except Exception:
        return None
    return cfg.evidence_manifest_file_id


def is_drive_evidence_enabled() -> bool:
    return os.getenv("DRIVE_EVIDENCE_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _resolve_client_id(
    client_id: str | None,
    *,
    user_principal_id: str | None,
) -> str | None:
    raw = str(client_id or "").strip()
    if not raw:
        return None
    aliases = load_client_aliases()
    mode = get_client_store_mode()
    if mode == "cosmos":
        try:
            candidates = list_qbo_client_ids(
                limit=200,
                user_principal_id=user_principal_id,
            )
        except Exception:
            candidates = []
        return resolve_client_id(raw, candidates, aliases)

    clients_cfg = _load_clients_file()
    candidates = list((clients_cfg.get("clients") or {}).keys())
    return resolve_client_id(raw, candidates, aliases)


def _load_client_drive_settings(
    client_id: str | None,
    *,
    user_principal_id: str | None,
) -> dict[str, Any]:
    if not client_id:
        return {}

    mode = get_client_store_mode()
    if mode == "cosmos":
        record = get_qbo_client_record(
            client_id,
            user_principal_id=user_principal_id,
        )
        if not isinstance(record, dict):
            return {}
        drive = record.get("drive")
        if isinstance(drive, dict):
            return drive
        return {}

    clients_cfg = _load_clients_file()
    entry = (clients_cfg.get("clients") or {}).get(client_id)
    if not isinstance(entry, dict):
        return {}
    drive = entry.get("drive")
    if isinstance(drive, dict):
        return drive
    return {}


def _load_clients_file() -> dict[str, Any]:
    path = _client_config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _client_config_path() -> Path:
    override = os.getenv("CLIENT_CONFIG_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "config" / "clients.json"


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _resolve_value(
    name: str,
    *,
    explicit: Any = None,
    allow_empty: bool,
) -> str:
    if explicit is not None:
        value = str(explicit).strip()
        if value or allow_empty:
            return value
    value = os.getenv(name, "").strip()
    if value or allow_empty:
        return value
    raise ValueError(f"Missing required environment variable: {name}")


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    cleaned = str(value).strip().lower()
    if cleaned in {"1", "true", "yes"}:
        return True
    if cleaned in {"0", "false", "no"}:
        return False
    return default
