from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from common.database.cosmos_util import get_cosmos_container_client
from common.models.reviews import BalanceSheetRunRecord
from common.telemetry import traced_phase

LOGGER = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_balance_sheet_run(
    *,
    run_id: str,
    user_principal_id: str | None,
    client_id: str,
    period_end: date,
    status: str,
    notes: str | None = None,
) -> BalanceSheetRunRecord:
    session_id = _session_id_for_run(user_principal_id, client_id)
    record = BalanceSheetRunRecord(
        id=run_id,
        session_id=session_id,
        user_principal_id=user_principal_id,
        client_id=client_id,
        period_end=period_end,
        status=status,
        created_at=_now(),
        notes=notes,
    )
    _upsert_record(record)
    return record


def update_balance_sheet_run(record: BalanceSheetRunRecord) -> BalanceSheetRunRecord:
    _upsert_record(record)
    return record


def get_balance_sheet_run(
    run_id: str,
    *,
    user_principal_id: str | None = None,
) -> Optional[BalanceSheetRunRecord]:
    container = get_cosmos_container_client()
    query = "SELECT * FROM c WHERE c.data_type=@data_type AND c.id=@run_id"
    params = [
        {"name": "@data_type", "value": "balance_sheet_run"},
        {"name": "@run_id", "value": run_id},
    ]
    if user_principal_id:
        query += " AND c.user_principal_id=@user_principal_id"
        params.append({"name": "@user_principal_id", "value": user_principal_id})
    with traced_phase(
        "dependency.cosmos.query_balance_sheet_run",
        attributes={"db.system": "cosmosdb"},
    ):
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
    if not items:
        return None
    return BalanceSheetRunRecord.model_validate(items[0])


def _upsert_record(record: BalanceSheetRunRecord) -> None:
    container = get_cosmos_container_client()
    payload = record.model_dump(mode="json")
    with traced_phase(
        "dependency.cosmos.upsert_balance_sheet_run",
        attributes={"db.system": "cosmosdb"},
    ):
        container.upsert_item(payload)


def _session_id_for_run(user_principal_id: str | None, client_id: str) -> str:
    user = str(user_principal_id or "").strip()
    if not user:
        return client_id
    return f"review_user::{user}::{client_id}"


def find_latest_balance_sheet_run_for_period(
    client_id: str,
    period_end: date,
    *,
    user_principal_id: str | None = None,
    exclude_failed: bool = True,
) -> Optional[BalanceSheetRunRecord]:
    """
    Return the most-recently created non-failed run for (client_id, period_end),
    or None if no matching run exists.

    Used by the idempotency guard in the MCP `get_or_create_balance_sheet_review`
    tool so that orchestrator retries/replans return the same run_id rather than
    spawning a new one.
    """
    container = get_cosmos_container_client()
    period_end_str = str(period_end)  # "YYYY-MM-DD"

    query = (
        "SELECT * FROM c "
        "WHERE c.data_type=@data_type "
        "AND c.client_id=@client_id "
        "AND c.period_end=@period_end"
    )
    params: list[dict] = [
        {"name": "@data_type", "value": "balance_sheet_run"},
        {"name": "@client_id", "value": client_id},
        {"name": "@period_end", "value": period_end_str},
    ]
    if user_principal_id:
        query += " AND c.user_principal_id=@user_principal_id"
        params.append({"name": "@user_principal_id", "value": user_principal_id})
    if exclude_failed:
        query += " AND c.status != 'failed'"
    query += " ORDER BY c.created_at DESC OFFSET 0 LIMIT 1"

    with traced_phase(
        "dependency.cosmos.find_latest_balance_sheet_run",
        attributes={"db.system": "cosmosdb"},
    ):
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
    if not items:
        return None
    return BalanceSheetRunRecord.model_validate(items[0])


def list_balance_sheet_runs_for_period(
    client_id: str,
    period_end: date,
    *,
    user_principal_id: str | None = None,
) -> List[BalanceSheetRunRecord]:
    """Return all runs (any status) for (client_id, period_end), newest first."""
    container = get_cosmos_container_client()
    period_end_str = str(period_end)

    query = (
        "SELECT * FROM c "
        "WHERE c.data_type=@data_type "
        "AND c.client_id=@client_id "
        "AND c.period_end=@period_end"
    )
    params: list[dict] = [
        {"name": "@data_type", "value": "balance_sheet_run"},
        {"name": "@client_id", "value": client_id},
        {"name": "@period_end", "value": period_end_str},
    ]
    if user_principal_id:
        query += " AND c.user_principal_id=@user_principal_id"
        params.append({"name": "@user_principal_id", "value": user_principal_id})
    query += " ORDER BY c.created_at DESC"

    with traced_phase(
        "dependency.cosmos.list_balance_sheet_runs_for_period",
        attributes={"db.system": "cosmosdb"},
    ):
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
    return [BalanceSheetRunRecord.model_validate(item) for item in items]
