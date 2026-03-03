"""Per-client correction memory — stores user feedback for contextual retrieval."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from common.database.cosmos_util import get_cosmos_container_client

LOGGER = logging.getLogger(__name__)


def save_correction(
    client_id: str,
    user_correction: str,
    correction_type: str,
    *,
    rule_id: str | None = None,
    account_ref: str | None = None,
    original_output: str = "",
    reasoning: str = "",
    created_by: str = "system",
    expires_months: int = 12,
    session_id: str = "corrections",
) -> dict:
    """Save a correction to Cosmos DB.

    Corrections are stored with client isolation and auto-expiry.
    They are surfaced as context in future reviews, never silently applied.
    """
    container = get_cosmos_container_client()
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "data_type": "correction",
        "client_id": client_id,
        "rule_id": rule_id,
        "account_ref": account_ref,
        "original_output": original_output,
        "user_correction": user_correction,
        "correction_type": correction_type,
        "reasoning": reasoning,
        "created_at": now.isoformat(),
        "created_by": created_by,
        "expires_at": (now + timedelta(days=expires_months * 30)).isoformat(),
        "active": True,
        "times_applied": 0,
        "last_applied_at": None,
    }
    container.upsert_item(doc)
    LOGGER.info(
        "Saved correction %s for client=%s rule=%s type=%s",
        doc["id"], client_id, rule_id, correction_type,
    )
    return doc


def get_corrections(
    client_id: str,
    *,
    rule_id: str | None = None,
    active_only: bool = True,
    max_results: int = 10,
) -> list[dict]:
    """Retrieve corrections for a client, optionally filtered by rule.

    Returns most recent corrections first, up to max_results.
    """
    container = get_cosmos_container_client()
    conditions = [
        "c.data_type = 'correction'",
        "c.client_id = @client_id",
    ]
    params: list[dict] = [{"name": "@client_id", "value": client_id}]

    if rule_id:
        conditions.append("(c.rule_id = @rule_id OR c.rule_id = null)")
        params.append({"name": "@rule_id", "value": rule_id})
    if active_only:
        conditions.append("c.active = true")

    query = (
        f"SELECT TOP {max_results} * FROM c "
        f"WHERE {' AND '.join(conditions)} "
        f"ORDER BY c.created_at DESC"
    )
    return list(
        container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )


def deactivate_correction(
    correction_id: str,
    session_id: str = "corrections",
) -> bool:
    """Soft-delete a correction by setting active=False."""
    container = get_cosmos_container_client()
    try:
        doc = container.read_item(item=correction_id, partition_key=session_id)
        doc["active"] = False
        container.upsert_item(doc)
        LOGGER.info("Deactivated correction %s", correction_id)
        return True
    except Exception:
        LOGGER.warning("Failed to deactivate correction %s", correction_id, exc_info=True)
        return False


def increment_applied(
    correction_id: str,
    session_id: str = "corrections",
) -> None:
    """Track that a correction was used in a review."""
    container = get_cosmos_container_client()
    try:
        doc = container.read_item(item=correction_id, partition_key=session_id)
        doc["times_applied"] = doc.get("times_applied", 0) + 1
        doc["last_applied_at"] = datetime.now(timezone.utc).isoformat()
        container.upsert_item(doc)
    except Exception:
        pass  # Non-critical — don't fail the review
