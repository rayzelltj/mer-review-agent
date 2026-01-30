from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .token_store import load_tokens, token_store_path


load_dotenv()


@dataclass(frozen=True)
class QBOConfig:
    env: str
    base_url: str
    client_id: str
    client_secret: str
    realm_id: str
    access_token: str
    refresh_token: str
    token_expires_at: str


def get_qbo_config() -> QBOConfig:
    """
    Load QBO connector configuration from environment variables.

    Skeleton stub only. Will read:
      QBO_ENV, QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REALM_ID,
      QBO_ACCESS_TOKEN, QBO_REFRESH_TOKEN, QBO_TOKEN_EXPIRES_AT
    """
    env = os.getenv("QBO_ENV", os.getenv("QBO_ENVIRONMENT", "sandbox")).strip().lower()
    base_url = _base_url_for_env(env)
    stored = load_tokens(token_store_path())

    return QBOConfig(
        env=env,
        base_url=base_url,
        client_id=_require_env("QBO_CLIENT_ID"),
        client_secret=_require_env("QBO_CLIENT_SECRET"),
        realm_id=_require_env("QBO_REALM_ID", stored),
        access_token=_require_env("QBO_ACCESS_TOKEN", stored),
        refresh_token=_require_env("QBO_REFRESH_TOKEN", stored),
        token_expires_at=_require_env("QBO_TOKEN_EXPIRES_AT", stored),
    )


def _base_url_for_env(env: str) -> str:
    if env == "sandbox":
        return "https://sandbox-quickbooks.api.intuit.com"
    if env == "production":
        return "https://quickbooks.api.intuit.com"
    raise ValueError("QBO_ENV must be 'sandbox' or 'production'.")


def _require_env(name: str, stored: dict[str, str] | None = None) -> str:
    if stored and name in stored and stored[name]:
        return stored[name]
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value
