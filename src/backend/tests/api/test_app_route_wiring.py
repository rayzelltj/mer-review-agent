from __future__ import annotations

import importlib
import sys
import types
from typing import Iterator

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from api import qbo, reviews


def _install_v4_stubs() -> None:
    router_mod = types.ModuleType("v4.api.router")
    router_mod.app_v4 = APIRouter(prefix="/api/v4")

    settings_mod = types.ModuleType("v4.config.settings")
    settings_mod.orchestration_config = types.SimpleNamespace(agent_wrappers={})

    registry_mod = types.ModuleType("v4.config.agent_registry")

    class _AgentRegistryStub:
        async def cleanup_all_agents(self) -> None:
            return None

    registry_mod.agent_registry = _AgentRegistryStub()

    sys.modules["v4.api.router"] = router_mod
    sys.modules["v4.config.settings"] = settings_mod
    sys.modules["v4.config.agent_registry"] = registry_mod


@pytest.fixture
def app_client(monkeypatch) -> Iterator[tuple[TestClient, object]]:
    _install_v4_stubs()
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")
    with TestClient(app_module.app) as client:
        yield client, app_module


def test_app_registers_reviews_and_qbo_routes(app_client):
    client, app_module = app_client
    paths = {route.path for route in app_module.app.routes}
    assert "/api/reviews/balance-sheet/run" in paths
    assert "/api/qbo/status" in paths
    assert "/api/qbo/callback" in paths


def test_app_readyz_includes_trace_header(app_client, monkeypatch):
    client, app_module = app_client
    monkeypatch.setattr(app_module, "current_trace_id", lambda: "trace-123")

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers.get("x-trace-id") == "trace-123"


def test_app_qbo_status_auth_error_propagates(app_client, monkeypatch):
    client, _ = app_client

    def _raise_unauthorized(_request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    monkeypatch.setattr(qbo, "_require_authenticated_user_id", _raise_unauthorized)

    response = client.get("/api/qbo/status?client_id=acme")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_app_reviews_run_conflict_propagates(app_client, monkeypatch):
    client, _ = app_client

    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _request: "user-1")
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")

    def _raise_conflict(*_args, **_kwargs):
        raise HTTPException(
            status_code=409,
            detail="QBO connection missing for client_id 'canonical_client'.",
        )

    monkeypatch.setattr(reviews, "_require_qbo_connection_http", _raise_conflict)

    response = client.post(
        "/api/reviews/balance-sheet/run",
        json={"client_id": "acme_alias", "period_end": "2025-12-31"},
    )

    assert response.status_code == 409
    assert "QBO connection missing" in response.json()["detail"]


def test_app_reviews_get_run_not_found(app_client, monkeypatch):
    client, _ = app_client

    async def _run_in_threadpool_direct(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        return func(*args, **kwargs)

    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _request: "user-1")
    monkeypatch.setattr(reviews, "run_in_threadpool", _run_in_threadpool_direct)
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: None)

    response = client.get("/api/reviews/balance-sheet/runs/run-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
