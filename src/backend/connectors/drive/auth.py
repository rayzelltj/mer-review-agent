from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from common.telemetry import traced_phase
from connectors.qbo.client_store import get_qbo_client_record
from connectors.qbo.config import get_client_store_mode

from .config import DriveConfig


TOKEN_URL = "https://oauth2.googleapis.com/token"


class DriveAuthError(RuntimeError):
    def __init__(self, message: str, body: str | None = None):
        super().__init__(message)
        self.body = body


def ensure_access_token_valid(config: DriveConfig) -> DriveConfig:
    if not config.access_token or _is_expired(config.token_expires_at):
        return refresh_access_token(config)
    return config


def refresh_access_token(config: DriveConfig) -> DriveConfig:
    token_payload = _post_refresh_token(config)
    access_token = str(token_payload.get("access_token") or "").strip()
    expires_in = token_payload.get("expires_in")
    refresh_token = str(token_payload.get("refresh_token") or config.refresh_token or "").strip()

    if not access_token or not expires_in:
        raise DriveAuthError(
            "Drive token refresh response missing required fields.",
            json.dumps(token_payload),
        )

    try:
        expires_seconds = int(expires_in)
    except Exception as exc:
        raise DriveAuthError("Drive token refresh returned invalid expires_in.", json.dumps(token_payload)) from exc

    updated = replace(
        config,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=_expires_at_from_seconds(expires_seconds),
    )
    _persist_tokens(updated)
    return updated


def _post_refresh_token(config: DriveConfig) -> dict[str, Any]:
    payload = urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": config.refresh_token,
        }
    ).encode("utf-8")

    req = Request(TOKEN_URL, data=payload, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with traced_phase(
            "dependency.drive.refresh_token",
            attributes={"http.url": TOKEN_URL, "http.method": "POST"},
        ):
            with urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else None
        raise DriveAuthError(f"Drive token refresh failed: {exc.code} {exc.reason}", body) from exc
    except URLError as exc:
        raise DriveAuthError(f"Drive token refresh failed: {exc}") from exc


def _persist_tokens(config: DriveConfig) -> None:
    os.environ["DRIVE_ACCESS_TOKEN"] = config.access_token
    os.environ["DRIVE_REFRESH_TOKEN"] = config.refresh_token
    os.environ["DRIVE_TOKEN_EXPIRES_AT"] = config.token_expires_at

    if get_client_store_mode() != "cosmos" or not config.client_record_id:
        return

    record = get_qbo_client_record(
        config.client_record_id,
        user_principal_id=config.user_principal_id,
    )
    if not isinstance(record, dict):
        return
    drive = record.get("drive")
    if not isinstance(drive, dict):
        drive = {}
    drive["refresh_token"] = config.refresh_token
    drive["access_token"] = config.access_token
    drive["token_expires_at"] = config.token_expires_at
    record["drive"] = drive

    try:
        from common.database.cosmos_util import get_cosmos_container_client

        container = get_cosmos_container_client()
        container.upsert_item(record)
    except Exception:
        return


def _is_expired(value: str) -> bool:
    parsed = _parse_expires(value)
    if parsed is None:
        return True
    now = datetime.now(timezone.utc)
    return parsed <= now + timedelta(seconds=30)


def _parse_expires(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
    except Exception:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _expires_at_from_seconds(seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.isoformat()
