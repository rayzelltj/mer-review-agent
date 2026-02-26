from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterable

import pytest
from fastapi import HTTPException

from api import reviews
from common.models.reviews import BalanceSheetRunRecord


async def _run_in_threadpool_direct(func, *args, **kwargs):  # type: ignore[no-untyped-def]
    return func(*args, **kwargs)


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={})


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


@pytest.fixture(autouse=True)
def _stub_auth_and_threadpool(monkeypatch):
    monkeypatch.setattr(reviews, "_authenticated_user_id", lambda _: "user-1")
    monkeypatch.setattr(reviews, "run_in_threadpool", _run_in_threadpool_direct)


@pytest.mark.asyncio
async def test_run_balance_sheet_review_queues_with_resolved_client_id(monkeypatch):
    calls: dict[str, Any] = {}

    class _FixedUUID:
        hex = "run-fixed-123"

    monkeypatch.setattr(reviews.uuid, "uuid4", lambda: _FixedUUID())
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")

    def _require_qbo_connection(client_id: str, *, user_principal_id: str | None):
        calls["precheck"] = {"client_id": client_id, "user_principal_id": user_principal_id}

    monkeypatch.setattr(reviews, "_require_qbo_connection_http", _require_qbo_connection)

    def _create_balance_sheet_run(**kwargs):
        calls["create_run_kwargs"] = kwargs
        return _record(
            run_id=kwargs["run_id"],
            status=kwargs["status"],
            client_id=kwargs["client_id"],
            period_end=kwargs["period_end"],
        )

    monkeypatch.setattr(reviews, "create_balance_sheet_run", _create_balance_sheet_run)

    scheduled: list[Any] = []

    def _fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(reviews.asyncio, "create_task", _fake_create_task)

    response = await reviews.run_balance_sheet_review(
        reviews.BalanceSheetRunRequest(client_id="acme_alias", period_end=date(2025, 12, 31), notes="focus cash"),
        _request(),
        # When the endpoint function is called directly (not via ASGI), FastAPI's
        # Query(False, alias="await") resolves to a truthy FieldInfo object rather
        # than the bool False.  Pass it explicitly to stay on the fire-and-forget path.
        await_result=False,
    )

    assert response.run_id == "run-fixed-123"
    assert response.status == "queued"
    assert calls["precheck"] == {"client_id": "canonical_client", "user_principal_id": "user-1"}
    assert calls["create_run_kwargs"]["client_id"] == "canonical_client"
    assert calls["create_run_kwargs"]["status"] == "queued"
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_run_balance_sheet_review_propagates_qbo_precheck_conflict(monkeypatch):
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")

    def _raise_precheck(*_args, **_kwargs):
        raise HTTPException(status_code=409, detail="QBO connection missing for client_id 'canonical_client'.")

    monkeypatch.setattr(reviews, "_require_qbo_connection_http", _raise_precheck)

    with pytest.raises(HTTPException) as excinfo:
        await reviews.run_balance_sheet_review(
            reviews.BalanceSheetRunRequest(client_id="acme_alias", period_end=date(2025, 12, 31)),
            _request(),
        )

    assert excinfo.value.status_code == 409
    assert "QBO connection missing" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_get_balance_sheet_review_returns_run_id_contract(monkeypatch):
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: _record(status="done"))

    payload = await reviews.get_balance_sheet_review("run-1", _request())

    assert payload["run_id"] == "run-1"
    assert "id" not in payload
    assert payload["status"] == "done"


@pytest.mark.asyncio
async def test_find_active_balance_sheet_review_uses_resolved_client_id(monkeypatch):
    calls: dict[str, Any] = {}

    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")

    def _find_latest(client_id: str, period_end: date, **kwargs):
        calls["find"] = {"client_id": client_id, "period_end": period_end, "kwargs": kwargs}
        return _record(run_id="run-existing", status="running", client_id=client_id, period_end=period_end)

    monkeypatch.setattr(reviews, "find_latest_balance_sheet_run_for_period", _find_latest)

    payload = await reviews.find_active_balance_sheet_review(
        client_id="acme_alias",
        period_end=date(2025, 12, 31),
        http_request=_request(),
    )

    assert payload["run_id"] == "run-existing"
    assert calls["find"]["client_id"] == "canonical_client"
    assert calls["find"]["kwargs"]["exclude_failed"] is True


@pytest.mark.asyncio
async def test_find_active_balance_sheet_review_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(reviews, "_resolve_client_id", lambda *_args, **_kwargs: "canonical_client")
    monkeypatch.setattr(
        reviews,
        "find_latest_balance_sheet_run_for_period",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(HTTPException) as excinfo:
        await reviews.find_active_balance_sheet_review(
            client_id="acme_alias",
            period_end=date(2025, 12, 31),
            http_request=_request(),
        )

    assert excinfo.value.status_code == 404
    assert str(excinfo.value.detail) == "No active run found"


@pytest.mark.asyncio
async def test_normalize_balance_sheet_run_rejects_queued_status(monkeypatch):
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: _record(status="queued"))

    with pytest.raises(HTTPException) as excinfo:
        await reviews.normalize_balance_sheet_run("run-1", _request())

    assert excinfo.value.status_code == 409
    assert "Fetch has not started yet" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_run_rules_for_review_rejects_queued_status(monkeypatch):
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: _record(status="queued"))

    with pytest.raises(HTTPException) as excinfo:
        await reviews.run_rules_for_review("run-1", reviews.RunRulesRequest(rule_ids=None), _request())

    assert excinfo.value.status_code == 409
    assert "not started yet" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_run_rules_for_review_runs_for_fetched_and_returns_updated_record(monkeypatch):
    records: Iterable[BalanceSheetRunRecord] = iter(
        [
            _record(run_id="run-1", status="fetched"),
            _record(run_id="run-1", status="done"),
        ]
    )
    monkeypatch.setattr(reviews, "get_balance_sheet_run", lambda *_args, **_kwargs: next(records))

    calls: dict[str, Any] = {}

    def _run_rules_phase_sync(**kwargs):
        calls["run_rules"] = kwargs

    monkeypatch.setattr(reviews, "_run_rules_phase_sync", _run_rules_phase_sync)

    payload = await reviews.run_rules_for_review(
        "run-1",
        reviews.RunRulesRequest(rule_ids=["BS-CASH-RECONCILES"]),
        _request(),
    )

    assert calls["run_rules"]["run_id"] == "run-1"
    assert calls["run_rules"]["user_principal_id"] == "user-1"
    assert calls["run_rules"]["rule_ids"] == {"BS-CASH-RECONCILES"}
    assert payload["run_id"] == "run-1"
    assert payload["status"] == "done"
