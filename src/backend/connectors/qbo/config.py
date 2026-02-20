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
    client_record_id: str | None = None
    user_principal_id: str | None = None


def get_qbo_config() -> QBOConfig:
    """
    Load QBO connector configuration from environment variables.

    Skeleton stub only. Will read:
      QBO_ENV, QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REALM_ID,
      QBO_ACCESS_TOKEN, QBO_REFRESH_TOKEN, QBO_TOKEN_EXPIRES_AT
    """
    return build_qbo_config()


def build_qbo_config(
    *,
    realm_id: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    token_expires_at: str | None = None,
    client_record_id: str | None = None,
    user_principal_id: str | None = None,
) -> QBOConfig:
    env = os.getenv("QBO_ENV", os.getenv("QBO_ENVIRONMENT", "sandbox")).strip().lower()
    base_url = _base_url_for_env(env)
    stored = load_tokens(token_store_path())

    return QBOConfig(
        env=env,
        base_url=base_url,
        client_id=_require_env("QBO_CLIENT_ID"),
        client_secret=_require_env("QBO_CLIENT_SECRET"),
        realm_id=_resolve_value("QBO_REALM_ID", realm_id, stored),
        access_token=_resolve_value("QBO_ACCESS_TOKEN", access_token, stored),
        refresh_token=_resolve_value("QBO_REFRESH_TOKEN", refresh_token, stored),
        token_expires_at=_resolve_value("QBO_TOKEN_EXPIRES_AT", token_expires_at, stored),
        client_record_id=client_record_id,
        user_principal_id=user_principal_id,
    )


def get_client_store_mode() -> str:
    mode = os.getenv("QBO_CLIENT_STORE", "").strip().lower()
    if mode in {"cosmos", "file"}:
        return mode
    if os.getenv("APP_ENV", "").strip().lower() == "dev":
        return "file"
    if os.getenv("COSMOSDB_ENDPOINT", "").strip():
        return "cosmos"
    return "file"


def _base_url_for_env(env: str) -> str:
    if env == "sandbox":
        return "https://sandbox-quickbooks.api.intuit.com"
    if env == "production":
        return "https://quickbooks.api.intuit.com"
    raise ValueError("QBO_ENV must be 'sandbox' or 'production'.")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _resolve_value(
    name: str,
    explicit: str | None,
    stored: dict[str, str] | None,
) -> str:
    if explicit is not None:
        return explicit
    if stored and name in stored and stored[name]:
        return stored[name]
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value
