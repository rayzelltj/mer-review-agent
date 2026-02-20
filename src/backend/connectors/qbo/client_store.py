from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Iterable

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from common.database.cosmos_util import get_cosmos_container_client
from common.client_id import load_client_aliases, resolve_client_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_qbo_client_record(
    client_id: str,
    *,
    user_principal_id: str | None = None,
) -> dict[str, Any] | None:
    if not client_id:
        return None
    normalized_user = _normalize_user_id(user_principal_id)
    record = _read_qbo_client_record(client_id, user_principal_id=normalized_user)
    if record:
        return record

    aliases = load_client_aliases()
    canonical = resolve_client_id(client_id, [], aliases)
    candidate_ids = [canonical, client_id]
    for alias in aliases.get(canonical, []) if canonical else []:
        candidate_ids.append(alias)

    seen: set[str] = set()
    for candidate in candidate_ids:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in seen or candidate == client_id:
            continue
        seen.add(candidate)
        record = _read_qbo_client_record(candidate, user_principal_id=normalized_user)
        if not record:
            continue
        if canonical and candidate != canonical:
            realm_id = str(record.get("realm_id") or "").strip()
            refresh_token = str(record.get("refresh_token") or "").strip()
            if realm_id and refresh_token:
                environment = str(
                    record.get("environment")
                    or os.getenv("QBO_ENV", os.getenv("QBO_ENVIRONMENT", "sandbox"))
                ).strip().lower()
                counterparties = record.get("counterparties") or []
                try:
                    upsert_qbo_client_tokens(
                        client_id=canonical,
                        user_principal_id=normalized_user,
                        realm_id=realm_id,
                        refresh_token=refresh_token,
                        environment=environment,
                        counterparties=counterparties,
                    )
                    migrated = _read_qbo_client_record(
                        canonical,
                        user_principal_id=normalized_user,
                    )
                    if migrated:
                        return migrated
                except Exception:
                    pass
        return record

    return None


def upsert_qbo_client_tokens(
    *,
    client_id: str,
    user_principal_id: str | None = None,
    realm_id: str,
    refresh_token: str,
    environment: str,
    counterparties: Iterable[dict[str, str]] | None = None,
) -> dict[str, Any]:
    container = get_cosmos_container_client()
    normalized_user = _normalize_user_id(user_principal_id)
    existing = _read_qbo_client_record(client_id, user_principal_id=normalized_user)
    partition_key = _record_partition_key(
        client_id,
        user_principal_id=normalized_user,
    )
    created_at = existing.get("created_at") if existing else _now_iso()
    record = {
        "id": _record_id(client_id, user_principal_id=normalized_user),
        "session_id": partition_key,
        "data_type": "qbo_client",
        "client_id": client_id,
        "user_principal_id": normalized_user,
        "realm_id": realm_id,
        "refresh_token": refresh_token,
        "environment": environment,
        "counterparties": list(counterparties or []),
        "created_at": created_at,
        "updated_at": _now_iso(),
    }
    container.upsert_item(record)
    return record


def update_refresh_token_for_realm(
    *,
    realm_id: str,
    refresh_token: str,
    user_principal_id: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any] | None:
    container = get_cosmos_container_client()
    normalized_user = _normalize_user_id(user_principal_id)

    if client_id:
        record = _read_qbo_client_record(client_id, user_principal_id=normalized_user)
        if record is not None:
            record["refresh_token"] = refresh_token
            record["updated_at"] = _now_iso()
            container.upsert_item(record)
            return record

    query = "SELECT * FROM c WHERE c.data_type=@data_type AND c.realm_id=@realm_id"
    params = [
        {"name": "@data_type", "value": "qbo_client"},
        {"name": "@realm_id", "value": realm_id},
    ]
    if normalized_user:
        query += " AND c.user_principal_id=@user_principal_id"
        params.append({"name": "@user_principal_id", "value": normalized_user})
    items = list(
        container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )
    if not items:
        return None
    record = items[0]
    record["refresh_token"] = refresh_token
    record["updated_at"] = _now_iso()
    container.upsert_item(record)
    return record


def list_qbo_client_ids(
    limit: int = 50,
    *,
    user_principal_id: str | None = None,
) -> list[str]:
    container = get_cosmos_container_client()
    query = "SELECT c.client_id FROM c WHERE c.data_type=@data_type"
    params = [{"name": "@data_type", "value": "qbo_client"}]
    normalized_user = _normalize_user_id(user_principal_id)
    if normalized_user:
        query += " AND c.user_principal_id=@user_principal_id"
        params.append({"name": "@user_principal_id", "value": normalized_user})
    items = container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True,
        max_item_count=max(limit, 1),
    )
    client_ids: list[str] = []
    aliases = load_client_aliases()
    for item in items:
        if len(client_ids) >= limit:
            break
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("client_id") or "").strip()
        if not raw_id:
            continue
        client_id = resolve_client_id(raw_id, [], aliases)
        if not client_id or client_id in client_ids:
            continue
        client_ids.append(client_id)
    return client_ids


def _read_qbo_client_record(
    client_id: str,
    *,
    user_principal_id: str | None = None,
) -> dict[str, Any] | None:
    container = get_cosmos_container_client()
    normalized_user = _normalize_user_id(user_principal_id)
    item_id = _record_id(client_id, user_principal_id=normalized_user)
    partition_key = _record_partition_key(client_id, user_principal_id=normalized_user)
    try:
        return container.read_item(item=item_id, partition_key=partition_key)
    except CosmosResourceNotFoundError:
        if not normalized_user or not _allow_legacy_fallback():
            return None
    try:
        legacy_id = _legacy_record_id(client_id)
        return container.read_item(item=legacy_id, partition_key=client_id)
    except CosmosResourceNotFoundError:
        return None


def _record_id(client_id: str, *, user_principal_id: str | None = None) -> str:
    normalized_user = _normalize_user_id(user_principal_id)
    if normalized_user:
        return f"qbo_client::{normalized_user}::{client_id}"
    return _legacy_record_id(client_id)


def _legacy_record_id(client_id: str) -> str:
    return f"qbo_client::{client_id}"


def _record_partition_key(client_id: str, *, user_principal_id: str | None = None) -> str:
    normalized_user = _normalize_user_id(user_principal_id)
    if normalized_user:
        return f"qbo_user::{normalized_user}::{client_id}"
    return client_id


def _normalize_user_id(user_principal_id: str | None) -> str | None:
    value = str(user_principal_id or "").strip()
    return value or None


def _allow_legacy_fallback() -> bool:
    value = os.getenv("QBO_LEGACY_RECORD_FALLBACK_ENABLED", "").strip().lower()
    return value in {"1", "true", "yes"}
