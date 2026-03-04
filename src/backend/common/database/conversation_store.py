"""Cosmos DB persistence for session conversation context.

Replaces the volatile in-memory ``workflow_last_run_context`` dict so that
follow-up context survives server restarts and container re-deployments.

Uses the same shared Cosmos container as review_store / correction_store
with ``data_type="session_context"`` for discrimination.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from common.database.cosmos_util import get_cosmos_container_client

LOGGER = logging.getLogger(__name__)

_DATA_TYPE = "session_context"


def _doc_id(user_id: str, session_id: str) -> str:
    """Deterministic document id — one context doc per user+session."""
    return f"ctx:{user_id}:{session_id}"


def _session_id_for_partition(user_id: str, session_id: str) -> str:
    """Cosmos partition key — reuse the session_id convention used elsewhere."""
    return f"{user_id}_{session_id}"


def save_session_context(
    *,
    user_id: str,
    session_id: str,
    run_id: str,
    initial_goal: str = "",
    client_id: str = "",
    period_end: str = "",
    review_summary: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Upsert session context to Cosmos DB.

    Safe to call on every run — uses Cosmos upsert so last-write-wins.
    """
    try:
        container = get_cosmos_container_client()
        doc = {
            "id": _doc_id(user_id, session_id),
            "session_id": _session_id_for_partition(user_id, session_id),
            "data_type": _DATA_TYPE,
            "user_id": user_id,
            "original_session_id": session_id,
            "run_id": run_id,
            "initial_goal": initial_goal,
            "client_id": client_id,
            "period_end": period_end,
            "review_summary": review_summary[:8000] if review_summary else "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            doc["extra"] = extra
        container.upsert_item(doc)
        LOGGER.info(
            "Saved session context user=%s session=%s run_id=%s summary_len=%d",
            user_id,
            session_id,
            run_id,
            len(review_summary or ""),
        )
    except Exception:
        LOGGER.exception(
            "Failed to save session context user=%s session=%s", user_id, session_id
        )


def get_session_context(
    user_id: str,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Load session context from Cosmos DB.  Returns None if not found."""
    try:
        container = get_cosmos_container_client()
        doc_id = _doc_id(user_id, session_id)
        partition = _session_id_for_partition(user_id, session_id)
        item = container.read_item(item=doc_id, partition_key=partition)
        LOGGER.info(
            "Loaded session context user=%s session=%s run_id=%s",
            user_id,
            session_id,
            item.get("run_id", "?"),
        )
        return item
    except CosmosResourceNotFoundError:
        LOGGER.debug(
            "No session context found user=%s session=%s", user_id, session_id
        )
        return None
    except Exception:
        LOGGER.exception(
            "Failed to load session context user=%s session=%s", user_id, session_id
        )
        return None


def delete_session_context(user_id: str, session_id: str) -> bool:
    """Remove session context.  Returns True if deleted, False otherwise."""
    try:
        container = get_cosmos_container_client()
        doc_id = _doc_id(user_id, session_id)
        partition = _session_id_for_partition(user_id, session_id)
        container.delete_item(item=doc_id, partition_key=partition)
        LOGGER.info("Deleted session context user=%s session=%s", user_id, session_id)
        return True
    except CosmosResourceNotFoundError:
        return False
    except Exception:
        LOGGER.exception(
            "Failed to delete session context user=%s session=%s", user_id, session_id
        )
        return False
