from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import qbo, reviews
from common.models.reviews import BalanceSheetRunRecord


def _record(
    *,
    run_id: str = "run-1",
    status: str = "queued",
    client_id: str = "acme_co",
    period_end: date = date(2025, 12, 31),
) -> BalanceSheetRunRecord:
    return BalanceSheetRunRecord(
        id=run_id,
        session_id=f"review_user::user-1::{client_id}",
        user_principal_id="user-1",
        client_id=client_id,
        period_end=period_end,
        status=status,  # type: ignore[arg-type]
        created_at=datetime.now(timezone.utc),
    )


async def _run_in_threadpool_direct(func, *args, **kwargs):  # type: ignore[no-untyped-def]
    return func(*args, **kwargs)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(reviews.router)
    app.include_router(qbo.api_router)
    monkeypatch.setattr(reviews, "run_in_threadpool", _run_in_threadpool_direct)
    return TestClient(app)


def test_reviews_run_route_returns_queued_with_run_id(client: TestClient, monkeypatch):
    class _FixedUUID:
        hex = "run-fixed-123"

    monkeypatch.setattr(reviews.uuid, "uuid4", lambda: _FixedUUID())
    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")
    monkeypatch.setattr(reviews, "_require_qbo_connection_http", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        reviews,
        "create_balance_sheet_run",
        lambda **kwargs: _record(
            run_id=kwargs["run_id"],
            status=kwargs["status"],
            client_id=kwargs["client_id"],
            period_end=kwargs["period_end"],
        ),
    )

    def _fake_create_task(coro):
        coro.close()
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(reviews.asyncio, "create_task", _fake_create_task)

    response = client.post(
        "/api/reviews/balance-sheet/run",
        json={"client_id": "acme_alias", "period_end": "2025-12-31"},
    )

    assert response.status_code == 200
    data = response.json()
    # The response may include additional optional fields (e.g. summary, findings)
    # that are None when the run is queued; only assert the required fields.
    assert data["run_id"] == "run-fixed-123"
    assert data["status"] == "queued"


def test_reviews_run_route_propagates_qbo_precheck_conflict(client: TestClient, monkeypatch):
    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")

    def _raise_conflict(*_args, **_kwargs):
        raise HTTPException(status_code=409, detail="QBO connection missing for client_id 'canonical_client'.")

    monkeypatch.setattr(reviews, "_require_qbo_connection_http", _raise_conflict)

    response = client.post(
        "/api/reviews/balance-sheet/run",
        json={"client_id": "acme_alias", "period_end": "2025-12-31"},
    )

    assert response.status_code == 409
    assert "QBO connection missing" in response.json()["detail"]


def test_reviews_get_run_contract_uses_run_id_field(client: TestClient, monkeypatch):
    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: _record(status="done"))

    response = client.get("/api/reviews/balance-sheet/runs/run-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-1"
    assert "id" not in payload
    assert payload["status"] == "done"


def test_reviews_find_returns_404_when_missing(client: TestClient, monkeypatch):
    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")
    monkeypatch.setattr(reviews, "find_latest_balance_sheet_run_for_period", lambda *_args, **_kwargs: None)

    response = client.get("/api/reviews/balance-sheet/find?client_id=acme&period_end=2025-12-31")

    assert response.status_code == 404
    assert response.json()["detail"] == "No active run found"


def test_reviews_run_rules_rejects_queued(client: TestClient, monkeypatch):
    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: _record(status="queued"))

    response = client.post("/api/reviews/balance-sheet/run-1/run-rules", json={})

    assert response.status_code == 409
    assert "not started yet" in response.json()["detail"]


def test_qbo_status_route_requires_auth(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        qbo,
        "_require_authenticated_user_id",
        lambda _request: (_ for _ in ()).throw(HTTPException(status_code=401, detail="Unauthorized")),
    )

    response = client.get("/api/qbo/status?client_id=acme")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_qbo_status_route_returns_connection_payload(client: TestClient, monkeypatch):
    monkeypatch.setattr(qbo, "_require_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(
        qbo,
        "_qbo_connection_status",
        lambda *_args, **_kwargs: {"connected": True, "store_mode": "cosmos", "client_id": "acme", "realm_id": "42"},
    )

    response = client.get("/api/qbo/status?client_id=acme")

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["client_id"] == "acme"


def test_qbo_callback_route_requires_auth(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        qbo,
        "_require_authenticated_user_id",
        lambda _request: (_ for _ in ()).throw(HTTPException(status_code=401, detail="Unauthorized")),
    )

    response = client.get("/api/qbo/callback?code=abc&realmId=123&state=state-1")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_qbo_callback_route_returns_success_contract(client: TestClient, monkeypatch):
    monkeypatch.setattr(qbo, "_require_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(
        qbo,
        "_handle_oauth_callback",
        lambda **_kwargs: {
            "status": "ok",
            "connected": True,
            "store_mode": "file",
            "client_id": "acme",
            "realm_id": "42",
            "token_expires_at": "2026-02-01T00:00:00+00:00",
        },
    )

    response = client.get("/api/qbo/callback?code=abc&realmId=123&state=state-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["connected"] is True
    assert payload["store_mode"] == "file"


def test_qbo_callback_route_returns_400_on_invalid_state(client: TestClient, monkeypatch):
    monkeypatch.setattr(qbo, "_require_authenticated_user_id", lambda _: "user-1")

    def _raise_invalid_state(**_kwargs):
        raise HTTPException(status_code=400, detail="Invalid or expired state.")

    monkeypatch.setattr(qbo, "_handle_oauth_callback", _raise_invalid_state)

    response = client.get("/api/qbo/callback?code=abc&realmId=123&state=state-1")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired state."
