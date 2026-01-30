from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from connectors.qbo.oauth import exchange_code_for_tokens
from connectors.qbo.token_store import persist_env, save_tokens, token_store_path


router = APIRouter(prefix="/qbo", tags=["qbo"])

_STATE_TTL_SECONDS = 600
_STATE_STORE: dict[str, dict[str, Any]] = {}


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing required environment variable: {name}")
    return value


def _get_redirect_uri(target: str | None) -> str:
    if target == "dev":
        return _require_env("QBO_REDIRECT_URI_DEV")
    return _require_env("QBO_REDIRECT_URI")


@router.get("/oauth/start")
def qbo_oauth_start(target: str | None = Query(None)):
    client_id = _require_env("QBO_CLIENT_ID")
    scopes = os.getenv("QBO_OAUTH_SCOPES", "com.intuit.quickbooks.accounting")
    redirect_uri = _get_redirect_uri(target)

    state = uuid.uuid4().hex
    _STATE_STORE[state] = {
        "created_at": time.time(),
        "redirect_uri": redirect_uri,
    }

    auth_url = "https://appcenter.intuit.com/connect/oauth2"
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return RedirectResponse(url=f"{auth_url}?{query}")


@router.get("/callback")
def qbo_oauth_callback(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
):
    record = _STATE_STORE.pop(state, None)
    if record is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state.")
    if time.time() - record["created_at"] > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="State expired.")

    redirect_uri = record["redirect_uri"]
    client_id = _require_env("QBO_CLIENT_ID")
    client_secret = _require_env("QBO_CLIENT_SECRET")

    payload = exchange_code_for_tokens(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code=code,
    )
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access_token or not refresh_token or not expires_in:
        raise HTTPException(status_code=502, detail="OAuth token exchange failed.")

    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()
    save_tokens(
        token_store_path(),
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=expires_at,
        realm_id=realmId,
    )
    persist_env(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=expires_at,
        realm_id=realmId,
    )

    return {
        "status": "ok",
        "realm_id": realmId,
        "token_expires_at": expires_at,
    }
