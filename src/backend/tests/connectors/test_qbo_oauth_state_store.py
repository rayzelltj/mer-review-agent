from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from api import qbo


def test_save_oauth_state_raises_when_cosmos_unavailable(monkeypatch):
    monkeypatch.setattr(qbo, "_use_cosmos_state", lambda: True)

    def _raise() -> Any:
        raise RuntimeError("cosmos unavailable")

    monkeypatch.setattr(qbo, "get_cosmos_container_client", _raise)

    with pytest.raises(HTTPException) as excinfo:
        qbo._save_oauth_state("state-1", {"created_at": 1.0})

    assert excinfo.value.status_code == 503
    assert "OAuth state store" in str(excinfo.value.detail)


def test_pop_oauth_state_returns_none_for_missing_state(monkeypatch):
    class NotFoundError(Exception):
        status_code = 404

    class FakeContainer:
        def read_item(self, item, partition_key):  # noqa: ANN001
            raise NotFoundError("not found")

    monkeypatch.setattr(qbo, "_use_cosmos_state", lambda: True)
    monkeypatch.setattr(qbo, "get_cosmos_container_client", lambda: FakeContainer())

    assert qbo._pop_oauth_state("missing-state") is None


def test_pop_oauth_state_raises_on_cosmos_read_failure(monkeypatch):
    class FakeContainer:
        def read_item(self, item, partition_key):  # noqa: ANN001
            raise RuntimeError("transport failure")

    monkeypatch.setattr(qbo, "_use_cosmos_state", lambda: True)
    monkeypatch.setattr(qbo, "get_cosmos_container_client", lambda: FakeContainer())

    with pytest.raises(HTTPException) as excinfo:
        qbo._pop_oauth_state("state-2")

    assert excinfo.value.status_code == 503
    assert "OAuth state" in str(excinfo.value.detail)


def test_exchange_tokens_for_callback_maps_qbo_auth_errors(monkeypatch):
    def _raise(**_: Any):
        raise qbo.QBOAuthError("invalid_grant")

    monkeypatch.setattr(qbo, "exchange_code_for_tokens", _raise)

    with pytest.raises(HTTPException) as excinfo:
        qbo._exchange_tokens_for_callback(
            app_client_id="client-id",
            client_secret="secret",
            redirect_uri="https://example/callback",
            code="abc",
        )

    assert excinfo.value.status_code == 502
    assert "token exchange failed" in str(excinfo.value.detail).lower()


def test_handle_oauth_callback_rejects_invalid_expires_in(monkeypatch):
    monkeypatch.setattr(
        qbo,
        "_pop_oauth_state",
        lambda _: {
            "created_at": time.time(),
            "redirect_uri": "https://example/callback",
            "client_id": "acme_co",
            "user_principal_id": "user-1",
        },
    )
    monkeypatch.setattr(qbo, "_resolve_client_id", lambda client_id, **_: client_id)
    monkeypatch.setattr(
        qbo,
        "_exchange_tokens_for_callback",
        lambda **_: {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": "not-a-number",
        },
    )
    monkeypatch.setattr(
        qbo,
        "_require_env",
        lambda name: "client-id" if name == "QBO_CLIENT_ID" else "client-secret",
    )

    with pytest.raises(HTTPException) as excinfo:
        qbo._handle_oauth_callback(
            code="code-123",
            realm_id="realm-123",
            state="state-123",
            client_id="acme_co",
            user_principal_id="user-1",
        )

    assert excinfo.value.status_code == 502
    assert "invalid expires_in" in str(excinfo.value.detail)


def test_handle_oauth_callback_surfaces_storage_failures(monkeypatch):
    monkeypatch.setattr(
        qbo,
        "_pop_oauth_state",
        lambda _: {
            "created_at": time.time(),
            "redirect_uri": "https://example/callback",
            "client_id": "acme_co",
            "user_principal_id": "user-1",
        },
    )
    monkeypatch.setattr(qbo, "_resolve_client_id", lambda client_id, **_: client_id)
    monkeypatch.setattr(
        qbo,
        "_exchange_tokens_for_callback",
        lambda **_: {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        qbo,
        "_require_env",
        lambda name: "client-id" if name == "QBO_CLIENT_ID" else "client-secret",
    )
    monkeypatch.setattr(qbo, "get_client_store_mode", lambda: "cosmos")

    def _raise(**_: Any):
        raise RuntimeError("cosmos write failed")

    monkeypatch.setattr(qbo, "upsert_qbo_client_tokens", _raise)

    with pytest.raises(HTTPException) as excinfo:
        qbo._handle_oauth_callback(
            code="code-123",
            realm_id="realm-123",
            state="state-123",
            client_id="acme_co",
            user_principal_id="user-1",
        )

    assert excinfo.value.status_code == 503
    assert "persist qbo connection" in str(excinfo.value.detail).lower()


def test_handle_oauth_callback_returns_connected_response(monkeypatch):
    monkeypatch.setattr(
        qbo,
        "_pop_oauth_state",
        lambda _: {
            "created_at": time.time(),
            "redirect_uri": "https://example/callback",
            "client_id": "acme_co",
            "user_principal_id": "user-1",
        },
    )
    monkeypatch.setattr(qbo, "_resolve_client_id", lambda client_id, **_: client_id)
    monkeypatch.setattr(
        qbo,
        "_exchange_tokens_for_callback",
        lambda **_: {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": "3600.0",
        },
    )
    monkeypatch.setattr(
        qbo,
        "_require_env",
        lambda name: "client-id" if name == "QBO_CLIENT_ID" else "client-secret",
    )
    monkeypatch.setattr(qbo, "get_client_store_mode", lambda: "file")
    monkeypatch.setattr(qbo, "token_store_path", lambda: "/tmp/qbo_tokens.json")
    monkeypatch.setattr(qbo, "save_tokens", lambda *args, **kwargs: None)
    monkeypatch.setattr(qbo, "persist_env", lambda **kwargs: None)

    payload = qbo._handle_oauth_callback(
        code="code-123",
        realm_id="realm-123",
        state="state-123",
        client_id="acme_co",
        user_principal_id="user-1",
    )

    assert payload["status"] == "ok"
    assert payload["connected"] is True
    assert payload["store_mode"] == "file"
    assert payload["client_id"] == "acme_co"
    assert payload["realm_id"] == "realm-123"


def test_qbo_validate_connection_reads_refresh_token_in_file_mode(monkeypatch):
    monkeypatch.setattr(qbo, "_require_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(
        qbo,
        "_qbo_connection_status",
        lambda *args, **kwargs: {
            "connected": True,
            "store_mode": "file",
            "client_id": "acme_co",
            "realm_id": "realm-123",
        },
    )
    monkeypatch.setattr(qbo, "load_tokens", lambda _: {"QBO_REFRESH_TOKEN": "refresh"})
    monkeypatch.setattr(qbo, "token_store_path", lambda: "/tmp/qbo_tokens.json")

    def _fake_build_qbo_config(**kwargs: Any):
        from connectors.qbo.config import QBOConfig

        return QBOConfig(
            env="sandbox",
            base_url="https://sandbox-quickbooks.api.intuit.com",
            client_id="client-id",
            client_secret="client-secret",
            realm_id=str(kwargs["realm_id"]),
            access_token="",
            refresh_token=str(kwargs["refresh_token"]),
            token_expires_at="",
            client_record_id=kwargs.get("client_record_id"),
            user_principal_id=kwargs.get("user_principal_id"),
        )

    monkeypatch.setattr("connectors.qbo.config.build_qbo_config", _fake_build_qbo_config)
    monkeypatch.setattr("connectors.qbo.client.qbo_get", lambda *args, **kwargs: {"ok": True})

    result = qbo.qbo_validate_connection(SimpleNamespace(headers={}), client_id="acme_co")

    assert result["connected"] is True
    assert result["live"] is True
