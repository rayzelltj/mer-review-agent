from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from auth.auth_utils import get_authenticated_user_details
from common.client_id import load_client_aliases, resolve_client_id, suggest_client_ids
from connectors.qbo.client_store import (
    get_qbo_client_record,
    list_qbo_client_ids,
    upsert_qbo_client_tokens,
)
from connectors.qbo.auth import QBOAuthError
from connectors.qbo.config import get_client_store_mode
from connectors.qbo.oauth import exchange_code_for_tokens
from connectors.qbo.token_store import load_tokens, persist_env, save_tokens, token_store_path
from common.database.cosmos_util import get_cosmos_container_client

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/qbo", tags=["qbo"])
api_router = APIRouter(prefix="/api/qbo", tags=["qbo"])

_STATE_TTL_SECONDS = 600
# In-memory state is only used in file-store/dev mode.
_STATE_STORE: dict[str, dict[str, Any]] = {}
_QBO_DEBUG_ENABLED = os.getenv("QBO_DEBUG_ENDPOINTS_ENABLED", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
_BLACKBIRD_CANONICAL = os.getenv("QBO_FILE_STORE_CLIENT_ID", "blackbird_fabrics").strip() or "blackbird_fabrics"

# ---------------------------------------------------------------------------
# Cosmos-backed OAuth state store
# Uses the same macae CosmosDB container; falls back to in-memory _STATE_STORE
# when Cosmos is not configured (dev/file mode).
# ---------------------------------------------------------------------------

def _use_cosmos_state() -> bool:
    return get_client_store_mode() == "cosmos"


def _save_oauth_state(state: str, record: dict[str, Any]) -> None:
    if _use_cosmos_state():
        try:
            container = get_cosmos_container_client()
            doc: dict[str, Any] = {
                "id": f"oauth_state::{state}",
                "session_id": f"oauth_state::{state}",
                "data_type": "qbo_oauth_state",
                "state": state,
                **record,
            }
            container.upsert_item(doc)
            return
        except Exception as exc:
            _LOGGER.exception("Cosmos OAuth state save failed for state=%s", state)
            raise HTTPException(
                status_code=503,
                detail="Unable to initialize QBO OAuth state store. Please retry.",
            ) from exc
    _STATE_STORE[state] = record


def _is_cosmos_not_found(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    kind = exc.__class__.__name__.lower()
    if "notfound" in kind:
        return True
    msg = str(exc).lower()
    return "not found" in msg and "404" in msg


def _pop_oauth_state(state: str) -> dict[str, Any] | None:
    if _use_cosmos_state():
        try:
            container = get_cosmos_container_client()
            doc_id = f"oauth_state::{state}"
            doc = container.read_item(item=doc_id, partition_key=doc_id)
            # Delete after read (one-shot use)
            try:
                container.delete_item(item=doc_id, partition_key=doc_id)
            except Exception:
                pass
            return {
                k: v
                for k, v in doc.items()
                if k
                not in {
                    "id",
                    "session_id",
                    "data_type",
                    "state",
                    "_rid",
                    "_self",
                    "_etag",
                    "_attachments",
                    "_ts",
                }
            }
        except Exception as exc:
            if _is_cosmos_not_found(exc):
                return None
            _LOGGER.exception("Cosmos OAuth state read failed for state=%s", state)
            raise HTTPException(
                status_code=503,
                detail="Unable to read QBO OAuth state. Please retry.",
            ) from exc
    return _STATE_STORE.pop(state, None)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing required environment variable: {name}")
    return value


def _get_redirect_uri(target: str | None) -> str:
    if target == "dev":
        return _require_env("QBO_REDIRECT_URI_DEV")
    return _require_env("QBO_REDIRECT_URI")


def _require_authenticated_user_id(request: Request) -> str:
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = str(authenticated_user.get("user_principal_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


def _resolve_client_id(
    client_id: str | None,
    *,
    user_principal_id: str,
) -> str | None:
    if not client_id:
        return client_id
    aliases = load_client_aliases()
    candidates: list[str] = []
    try:
        candidates = list_qbo_client_ids(user_principal_id=user_principal_id)
    except Exception:
        candidates = []
    return resolve_client_id(client_id, candidates, aliases)


def _start_oauth_flow(
    *,
    client_id: str | None,
    target: str | None,
    user_principal_id: str,
):
    authorization_url, _ = _build_oauth_authorization_url(
        client_id=client_id,
        target=target,
        user_principal_id=user_principal_id,
    )
    return RedirectResponse(url=authorization_url)


def _build_oauth_authorization_url(
    *,
    client_id: str | None,
    target: str | None,
    user_principal_id: str,
) -> tuple[str, str | None]:
    app_client_id = _require_env("QBO_CLIENT_ID")
    scopes = os.getenv("QBO_OAUTH_SCOPES", "com.intuit.quickbooks.accounting")
    redirect_uri = _get_redirect_uri(target)
    resolved_client_id = _resolve_client_id(client_id, user_principal_id=user_principal_id)

    state = uuid.uuid4().hex
    record: dict[str, Any] = {
        "created_at": time.time(),
        "redirect_uri": redirect_uri,
        "client_id": resolved_client_id,
        "requested_client_id": client_id,
        "user_principal_id": user_principal_id,
    }
    _save_oauth_state(state, record)

    auth_url = "https://appcenter.intuit.com/connect/oauth2"
    query = urlencode(
        {
            "client_id": app_client_id,
            "response_type": "code",
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{auth_url}?{query}", resolved_client_id


def _prepare_oauth_flow(
    *,
    client_id: str | None,
    target: str | None,
    user_principal_id: str,
):
    authorization_url, resolved_client_id = _build_oauth_authorization_url(
        client_id=client_id,
        target=target,
        user_principal_id=user_principal_id,
    )
    return {
        "authorization_url": authorization_url,
        "client_id": resolved_client_id or client_id,
    }


def _parse_expires_in_seconds(expires_in: Any) -> int:
    value = expires_in
    if isinstance(value, bool):
        value = None
    if isinstance(value, str):
        value = value.strip()
        if "." in value:
            try:
                value = float(value)
            except ValueError:
                value = None
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="OAuth token exchange returned invalid expires_in.") from exc
    if seconds <= 0:
        raise HTTPException(status_code=502, detail="OAuth token exchange returned invalid expires_in.")
    return seconds


def _exchange_tokens_for_callback(
    *,
    app_client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    try:
        payload = exchange_code_for_tokens(
            client_id=app_client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
    except QBOAuthError as exc:
        _LOGGER.warning("QBO OAuth token exchange rejected by Intuit: %s", exc)
        raise HTTPException(status_code=502, detail="QBO OAuth token exchange failed.") from exc
    except Exception as exc:
        _LOGGER.exception("Unexpected QBO OAuth token exchange failure")
        raise HTTPException(status_code=502, detail="QBO OAuth token exchange failed.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="OAuth token exchange failed.")
    return payload


def _handle_oauth_callback(
    *,
    code: str,
    realm_id: str,
    state: str,
    client_id: str | None,
    user_principal_id: str,
):
    record = _pop_oauth_state(state)
    if record is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state.")
    created_at = record.get("created_at")
    if not isinstance(created_at, (int, float)):
        raise HTTPException(status_code=400, detail="Invalid OAuth state payload.")
    if time.time() - created_at > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="State expired.")
    if str(record.get("user_principal_id") or "").strip() != user_principal_id:
        raise HTTPException(status_code=403, detail="OAuth state does not match signed-in user.")

    redirect_uri = record["redirect_uri"]
    client_id = record.get("client_id") or client_id
    client_id = _resolve_client_id(client_id, user_principal_id=user_principal_id)

    app_client_id = _require_env("QBO_CLIENT_ID")
    client_secret = _require_env("QBO_CLIENT_SECRET")

    payload = _exchange_tokens_for_callback(
        app_client_id=app_client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code=code,
    )
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = _parse_expires_in_seconds(payload.get("expires_in"))
    if not access_token or not refresh_token:
        raise HTTPException(status_code=502, detail="OAuth token exchange failed.")

    mode = get_client_store_mode()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    if mode == "cosmos":
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id is required for Cosmos token storage.")
        env = os.getenv("QBO_ENV", os.getenv("QBO_ENVIRONMENT", "sandbox")).strip().lower()
        try:
            upsert_qbo_client_tokens(
                client_id=client_id,
                user_principal_id=user_principal_id,
                realm_id=realm_id,
                refresh_token=refresh_token,
                environment=env,
            )
        except Exception as exc:
            _LOGGER.exception("Unable to persist QBO tokens in Cosmos for client=%s", client_id)
            raise HTTPException(status_code=503, detail="Unable to persist QBO connection. Please retry.") from exc
    else:
        try:
            save_tokens(
                token_store_path(),
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
                realm_id=realm_id,
            )
            persist_env(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
                realm_id=realm_id,
            )
        except Exception as exc:
            _LOGGER.exception("Unable to persist QBO tokens in file store")
            raise HTTPException(status_code=503, detail="Unable to persist QBO connection. Please retry.") from exc

    return {
        "status": "ok",
        "connected": True,
        "store_mode": mode,
        "client_id": client_id,
        "realm_id": realm_id,
        "token_expires_at": expires_at,
    }

def _qbo_connection_status(
    client_id: str | None,
    *,
    user_principal_id: str,
) -> dict[str, Any]:
    requested_client_id = client_id
    resolved_client_id = _resolve_client_id(client_id, user_principal_id=user_principal_id)
    if resolved_client_id:
        client_id = resolved_client_id
    mode = get_client_store_mode()
    if mode == "cosmos":
        if not client_id:
            return {
                "connected": False,
                "reason": "client_id is required",
                "store_mode": mode,
                "requested_client_id": requested_client_id,
                "resolved_client_id": resolved_client_id,
            }
        record = get_qbo_client_record(client_id, user_principal_id=user_principal_id)
        if not record:
            suggestions: list[str] = []
            try:
                suggestions = suggest_client_ids(
                    client_id,
                    list_qbo_client_ids(user_principal_id=user_principal_id),
                )
            except Exception:
                suggestions = []
            return {
                "connected": False,
                "reason": "no record found",
                "store_mode": mode,
                "client_id": client_id,
                "requested_client_id": requested_client_id,
                "resolved_client_id": resolved_client_id,
                "suggested_client_ids": suggestions,
            }
        realm_id = str(record.get("realm_id") or "").strip()
        refresh_token = str(record.get("refresh_token") or "").strip()
        if not realm_id or not refresh_token:
            return {
                "connected": False,
                "reason": "missing realm_id or refresh_token",
                "store_mode": mode,
                "client_id": client_id,
                "requested_client_id": requested_client_id,
                "resolved_client_id": resolved_client_id,
                "realm_id": realm_id or None,
            }
        return {
            "connected": True,
            "store_mode": mode,
            "client_id": client_id,
            "requested_client_id": requested_client_id,
            "resolved_client_id": resolved_client_id,
            "realm_id": realm_id,
        }

    tokens = load_tokens(token_store_path()) or {}
    realm_id = (tokens.get("QBO_REALM_ID") or os.getenv("QBO_REALM_ID", "")).strip()
    refresh_token = (tokens.get("QBO_REFRESH_TOKEN") or os.getenv("QBO_REFRESH_TOKEN", "")).strip()
    if realm_id and refresh_token:
        return {
            "connected": True,
            "store_mode": mode,
            "client_id": client_id,
            "requested_client_id": requested_client_id,
            "resolved_client_id": resolved_client_id,
            "realm_id": realm_id,
        }
    return {
        "connected": False,
        "reason": "missing realm_id or refresh_token",
        "store_mode": mode,
        "client_id": client_id,
        "requested_client_id": requested_client_id,
        "resolved_client_id": resolved_client_id,
        "realm_id": realm_id or None,
    }


def _qbo_connected_clients(
    *,
    user_principal_id: str,
) -> dict[str, Any]:
    if not _QBO_DEBUG_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    mode = get_client_store_mode()
    clients: list[dict[str, Any]] = []
    if mode == "cosmos":
        for candidate_id in list_qbo_client_ids(
            limit=200,
            user_principal_id=user_principal_id,
        ):
            resolved = _resolve_client_id(
                candidate_id,
                user_principal_id=user_principal_id,
            ) or candidate_id
            record = get_qbo_client_record(
                resolved,
                user_principal_id=user_principal_id,
            )
            if not record:
                continue
            realm_id = str(record.get("realm_id") or "").strip()
            refresh_token = str(record.get("refresh_token") or "").strip()
            clients.append(
                {
                    "client_id": resolved,
                    "requested_client_id": candidate_id,
                    "realm_id": realm_id or None,
                    "connected": bool(realm_id and refresh_token),
                    "has_refresh_token": bool(refresh_token),
                }
            )
        clients.sort(key=lambda item: str(item.get("client_id") or ""))
        return {"store_mode": mode, "clients": clients}

    tokens = load_tokens(token_store_path()) or {}
    realm_id = str(tokens.get("QBO_REALM_ID") or os.getenv("QBO_REALM_ID", "")).strip()
    refresh_token = str(
        tokens.get("QBO_REFRESH_TOKEN") or os.getenv("QBO_REFRESH_TOKEN", "")
    ).strip()
    clients.append(
        {
            "client_id": _BLACKBIRD_CANONICAL,
            "realm_id": realm_id or None,
            "connected": bool(realm_id and refresh_token),
            "has_refresh_token": bool(refresh_token),
        }
    )
    return {"store_mode": mode, "clients": clients}


@router.get("/oauth/start")
def qbo_oauth_start(
    request: Request,
    target: str | None = Query(None),
    client_id: str | None = Query(None),
):
    user_principal_id = _require_authenticated_user_id(request)
    return _start_oauth_flow(
        client_id=client_id,
        target=target,
        user_principal_id=user_principal_id,
    )


@api_router.get("/connect/start")
def qbo_connect_start(
    request: Request,
    client_id: str = Query(...),
    target: str | None = Query(None),
):
    user_principal_id = _require_authenticated_user_id(request)
    return _start_oauth_flow(
        client_id=client_id,
        target=target,
        user_principal_id=user_principal_id,
    )


@api_router.get("/connect/prepare")
def qbo_connect_prepare(
    request: Request,
    client_id: str = Query(...),
    target: str | None = Query(None),
):
    user_principal_id = _require_authenticated_user_id(request)
    return _prepare_oauth_flow(
        client_id=client_id,
        target=target,
        user_principal_id=user_principal_id,
    )


@api_router.get("/status")
def qbo_connection_status(request: Request, client_id: str | None = Query(None)):
    user_principal_id = _require_authenticated_user_id(request)
    return _qbo_connection_status(client_id, user_principal_id=user_principal_id)


@api_router.get("/validate")
def qbo_validate_connection(request: Request, client_id: str | None = Query(None)):
    """
    Check QBO connectivity AND verify the stored refresh token is still live
    against Intuit's API.  Returns:
      { connected: true, live: true }                       – all good
      { connected: true, live: false, reason: "token_expired" }  – stored but expired
      { connected: false, reason: "no_record" | ... }       – not stored at all
    """
    user_principal_id = _require_authenticated_user_id(request)
    status = _qbo_connection_status(client_id, user_principal_id=user_principal_id)

    if not status.get("connected"):
        return {**status, "live": False}

    # Attempt a cheap live probe: fetch CompanyInfo for the realm.
    realm_id = str(status.get("realm_id") or "").strip()
    resolved_client_id = str(status.get("client_id") or status.get("resolved_client_id") or "").strip()
    mode = str(status.get("store_mode") or get_client_store_mode()).strip().lower()
    try:
        from connectors.qbo.config import build_qbo_config
        from connectors.qbo.client import qbo_get

        refresh_token = ""
        env: str | None = None
        if mode == "cosmos":
            record = (
                get_qbo_client_record(resolved_client_id or client_id, user_principal_id=user_principal_id)
                if (resolved_client_id or client_id)
                else None
            )
            refresh_token = str((record or {}).get("refresh_token") or "").strip()
            env = str((record or {}).get("environment") or "").strip() or None
        else:
            tokens = load_tokens(token_store_path()) or {}
            refresh_token = str(
                tokens.get("QBO_REFRESH_TOKEN") or os.getenv("QBO_REFRESH_TOKEN", "")
            ).strip()
            env = os.getenv("QBO_ENV", os.getenv("QBO_ENVIRONMENT", "")).strip().lower() or None

        if not refresh_token:
            return {**status, "live": False, "reason": "no_refresh_token"}

        config = build_qbo_config(
            realm_id=realm_id,
            refresh_token=refresh_token,
            access_token="",
            token_expires_at="",
            client_record_id=resolved_client_id or client_id,
            user_principal_id=user_principal_id,
        )
        if env:
            config = config.__class__(
                env=env,
                base_url=config.base_url if env == config.env else (
                    "https://sandbox-quickbooks.api.intuit.com" if env == "sandbox"
                    else "https://quickbooks.api.intuit.com"
                ),
                client_id=config.client_id,
                client_secret=config.client_secret,
                realm_id=config.realm_id,
                access_token=config.access_token,
                refresh_token=config.refresh_token,
                token_expires_at=config.token_expires_at,
                client_record_id=config.client_record_id,
                user_principal_id=config.user_principal_id,
            )

        qbo_get(config, f"/v3/company/{realm_id}/companyinfo/{realm_id}", params={"minorversion": "65"})
        return {**status, "live": True}

    except Exception as exc:
        err_str = str(exc)
        is_auth_err = "401" in err_str or "403" in err_str or "token" in err_str.lower()
        reason = "token_expired" if is_auth_err else "probe_failed"
        _LOGGER.warning("QBO live probe failed for client=%s: %s", resolved_client_id or client_id, exc)
        return {**status, "live": False, "reason": reason, "detail": err_str}


@api_router.get("/debug/clients")
def qbo_connected_clients(request: Request):
    user_principal_id = _require_authenticated_user_id(request)
    return _qbo_connected_clients(user_principal_id=user_principal_id)


@router.get("/callback")
def qbo_oauth_callback(
    request: Request,
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
    client_id: str | None = Query(None),
):
    user_principal_id = _require_authenticated_user_id(request)
    return _handle_oauth_callback(
        code=code,
        realm_id=realmId,
        state=state,
        client_id=client_id,
        user_principal_id=user_principal_id,
    )


@api_router.get("/callback")
def qbo_connect_callback(
    request: Request,
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
    client_id: str | None = Query(None),
):
    user_principal_id = _require_authenticated_user_id(request)
    return _handle_oauth_callback(
        code=code,
        realm_id=realmId,
        state=state,
        client_id=client_id,
        user_principal_id=user_principal_id,
    )
