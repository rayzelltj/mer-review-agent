from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import QBOConfig
from .token_store import save_tokens, token_store_path


TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


class QBOAuthError(RuntimeError):
    def __init__(self, message: str, body: str | None = None):
        super().__init__(message)
        self.body = body


def refresh_access_token(config: QBOConfig) -> QBOConfig:
    """
    Refresh the access token using QBO OAuth refresh flow.

    Skeleton stub only. Should:
      - call Intuit token endpoint
      - update access_token/refresh_token/expires_at
      - persist updates (env or storage)
    """
    token_payload = _post_refresh_token(config)
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    expires_in = token_payload.get("expires_in")
    if not access_token or not refresh_token or not expires_in:
        raise QBOAuthError("Token refresh response missing required fields.", json.dumps(token_payload))

    expires_at = _expires_at_from_seconds(int(expires_in))
    updated = QBOConfig(
        env=config.env,
        base_url=config.base_url,
        client_id=config.client_id,
        client_secret=config.client_secret,
        realm_id=config.realm_id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=expires_at,
    )
    _persist_tokens(updated)
    return updated


def ensure_access_token_valid(config: QBOConfig) -> QBOConfig:
    """
    Ensure access token is valid; refresh if expired.
    """
    if _is_expired(config.token_expires_at):
        return refresh_access_token(config)
    return config


def _post_refresh_token(config: QBOConfig) -> dict[str, Any]:
    data = urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": config.refresh_token,
        }
    ).encode("utf-8")
    auth_raw = f"{config.client_id}:{config.client_secret}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("utf-8")

    req = Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", f"Basic {auth_b64}")

    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else None
        raise QBOAuthError(f"Token refresh failed: {exc.code} {exc.reason}", body) from exc
    except URLError as exc:
        raise QBOAuthError(f"Token refresh failed: {exc}") from exc


def _is_expired(value: str) -> bool:
    parsed = _parse_expires(value)
    if parsed is None:
        return True
    now = datetime.now(timezone.utc)
    return parsed <= now


def _parse_expires(value: str) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    try:
        if v.isdigit():
            return datetime.fromtimestamp(int(v), tz=timezone.utc)
    except ValueError:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _expires_at_from_seconds(seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.isoformat()


def _persist_tokens(config: QBOConfig) -> None:
    os.environ["QBO_ACCESS_TOKEN"] = config.access_token
    os.environ["QBO_REFRESH_TOKEN"] = config.refresh_token
    os.environ["QBO_TOKEN_EXPIRES_AT"] = config.token_expires_at

    env_file = os.getenv("QBO_ENV_FILE", ".env")
    if not os.path.exists(env_file):
        env_file = None
    _update_env_file(
        env_file,
        {
            "QBO_ACCESS_TOKEN": config.access_token,
            "QBO_REFRESH_TOKEN": config.refresh_token,
            "QBO_TOKEN_EXPIRES_AT": config.token_expires_at,
            "QBO_REALM_ID": config.realm_id,
        },
    )
    save_tokens(
        token_store_path(),
        access_token=config.access_token,
        refresh_token=config.refresh_token,
        token_expires_at=config.token_expires_at,
        realm_id=config.realm_id,
    )


def _update_env_file(path: str | None, updates: dict[str, str]) -> None:
    if path is None:
        return
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}\n")
        else:
            new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}\n")

    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(new_lines)
