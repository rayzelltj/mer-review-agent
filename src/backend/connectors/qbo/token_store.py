from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


TOKEN_STORE_DEFAULT = ".qbo_tokens.json"


def token_store_path() -> str:
    return os.getenv("QBO_TOKEN_STORE_PATH", TOKEN_STORE_DEFAULT)


def load_tokens(path: str) -> dict[str, str] | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.loads(handle.read())
    if not isinstance(raw, dict):
        return None
    return {k: str(v) for k, v in raw.items() if v is not None}


def save_tokens(
    path: str,
    *,
    access_token: str,
    refresh_token: str,
    token_expires_at: str,
    realm_id: str,
) -> None:
    data: dict[str, Any] = {
        "QBO_ACCESS_TOKEN": access_token,
        "QBO_REFRESH_TOKEN": refresh_token,
        "QBO_TOKEN_EXPIRES_AT": token_expires_at,
        "QBO_REALM_ID": realm_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def persist_env(
    *,
    access_token: str,
    refresh_token: str,
    token_expires_at: str,
    realm_id: str,
) -> None:
    os.environ["QBO_ACCESS_TOKEN"] = access_token
    os.environ["QBO_REFRESH_TOKEN"] = refresh_token
    os.environ["QBO_TOKEN_EXPIRES_AT"] = token_expires_at
    os.environ["QBO_REALM_ID"] = realm_id
