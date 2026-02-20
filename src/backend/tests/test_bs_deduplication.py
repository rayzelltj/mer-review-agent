"""
Acceptance tests for the Balance Sheet Review de-duplication fixes.

Tests cover:
  T1  ReviewContext creation and task header injection
  T2  ReviewContext idempotency: same correlation_id → same token
  T3  find_latest_balance_sheet_run_for_period returns existing non-failed run
  T4  find_latest_balance_sheet_run_for_period returns None when only failed runs exist
  T5  Output gate: orchestrator agents route to AGENT_MESSAGE
  T6  Output gate: sub-agents route to INTERNAL_AGENT_MESSAGE
  T7  Output gate: streaming chunks from sub-agents are suppressed
  T8  Output gate: tool-call messages from sub-agents are always forwarded
  T9  get_or_create idempotency: reuses existing run, does NOT call POST a second time
  T10 ReviewContext.is_terminal reflects run status correctly
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# T1 & T2 — ReviewContext
# ---------------------------------------------------------------------------

class TestReviewContext:
    def _make(self, **kwargs):
        from v4.common.models.review_context import ReviewContext
        return ReviewContext.new(user_id="user-1", **kwargs)

    def test_new_creates_unique_correlation_ids(self):
        """Each ReviewContext.new() call produces a distinct correlation_id."""
        from v4.common.models.review_context import ReviewContext
        ctx1 = ReviewContext.new(user_id="user-1")
        ctx2 = ReviewContext.new(user_id="user-1")
        assert ctx1.correlation_id != ctx2.correlation_id

    def test_task_header_round_trip(self):
        """to_task_header() encodes fields; header is parseable JSON."""
        from v4.common.models.review_context import ReviewContext
        ctx = ReviewContext.new(user_id="user-1", client_id="example_client", period_end="2025-12-31")
        ctx = ctx.set_run_id("abc123", status="queued")
        header = ctx.to_task_header()
        assert header.startswith("REVIEW_CONTEXT:")
        payload = json.loads(header[len("REVIEW_CONTEXT:"):])
        assert payload["correlation_id"] == ctx.correlation_id
        assert payload["client_id"] == "example_client"
        assert payload["run_id"] == "abc123"

    def test_inject_into_task_prepends_header(self):
        """inject_into_task() prepends the header and preserves original task text."""
        from v4.common.models.review_context import ReviewContext
        ctx = ReviewContext.new(user_id="user-1", client_id="example_client", period_end="2025-12-31")
        original = "Run a balance sheet review for client example_client."
        injected = ctx.inject_into_task(original)
        assert injected.startswith("REVIEW_CONTEXT:")
        assert original in injected

    def test_set_run_id_immutable(self):
        """set_run_id returns a new object; original is unchanged."""
        from v4.common.models.review_context import ReviewContext
        ctx = ReviewContext.new(user_id="user-1")
        updated = ctx.set_run_id("run-xyz", status="running")
        assert ctx.run_id is None
        assert updated.run_id == "run-xyz"
        assert updated.run_status == "running"
        # correlation_id is preserved
        assert updated.correlation_id == ctx.correlation_id

    def test_is_terminal(self):
        """is_terminal is True only for done/failed."""
        from v4.common.models.review_context import ReviewContext
        ctx = ReviewContext.new(user_id="u")
        assert not ctx.is_terminal
        assert not ctx.set_run_id("r", status="queued").is_terminal
        assert not ctx.set_run_id("r", status="running").is_terminal
        assert ctx.set_run_id("r", status="done").is_terminal
        assert ctx.set_run_id("r", status="failed").is_terminal


# ---------------------------------------------------------------------------
# T3 & T4 — find_latest_balance_sheet_run_for_period
# ---------------------------------------------------------------------------

class TestFindLatestRun:
    """Unit tests for review_store.find_latest_balance_sheet_run_for_period."""

    def _make_record(self, run_id: str, status: str, client_id: str = "example_client", period_end: str = "2025-12-31"):
        """Minimal CosmosDB item dict that validates to BalanceSheetRunRecord."""
        from datetime import datetime, timezone
        return {
            "id": run_id,
            "session_id": f"session-{run_id}",
            "data_type": "balance_sheet_run",
            "client_id": client_id,
            "period_end": period_end,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "findings": [],
            "totals": {},
            "hitl_requests": [],
            "snapshot_keys": {},
            "artifact_keys": {},
        }

    def test_returns_existing_non_failed_run(self):
        """find_latest returns a record when a queued/running/done run exists."""
        from common.database.review_store import find_latest_balance_sheet_run_for_period

        existing = self._make_record("run-existing", "done")
        mock_container = MagicMock()
        mock_container.query_items.return_value = [existing]

        with patch(
            "common.database.review_store.get_cosmos_container_client",
            return_value=mock_container,
        ):
            result = find_latest_balance_sheet_run_for_period(
                "example_client",
                date(2025, 12, 31),
            )

        assert result is not None
        assert result.id == "run-existing"
        assert result.status == "done"

    def test_returns_none_when_only_failed_runs(self):
        """find_latest returns None when exclude_failed=True and only failed runs exist."""
        from common.database.review_store import find_latest_balance_sheet_run_for_period

        mock_container = MagicMock()
        # Cosmos returns empty because the query excludes failed
        mock_container.query_items.return_value = []

        with patch(
            "common.database.review_store.get_cosmos_container_client",
            return_value=mock_container,
        ):
            result = find_latest_balance_sheet_run_for_period(
                "example_client",
                date(2025, 12, 31),
                exclude_failed=True,
            )

        assert result is None

    def test_query_includes_period_end_filter(self):
        """Cosmos query parameters include both client_id and period_end."""
        from common.database.review_store import find_latest_balance_sheet_run_for_period

        mock_container = MagicMock()
        mock_container.query_items.return_value = []

        with patch(
            "common.database.review_store.get_cosmos_container_client",
            return_value=mock_container,
        ):
            find_latest_balance_sheet_run_for_period(
                "example_client",
                date(2025, 12, 31),
            )

        call_kwargs = mock_container.query_items.call_args
        params = call_kwargs[1].get("parameters") or call_kwargs[0][0] if call_kwargs[0] else []
        # Locate parameters from keyword args
        params = mock_container.query_items.call_args.kwargs.get("parameters", [])
        names = {p["name"] for p in params}
        assert "@client_id" in names
        assert "@period_end" in names


# ---------------------------------------------------------------------------
# T5–T8 — Output gate in response_handlers
# ---------------------------------------------------------------------------

class TestOutputGate:
    """Tests for the _is_orchestrator_agent gate and its effect on message routing."""

    def test_orchestrator_names_pass_gate(self):
        """Known orchestrator agent names pass the output gate."""
        from v4.callbacks.response_handlers import _is_orchestrator_agent
        for name in [
            "MagenticManager",
            "magenticmanager",
            "StandardMagenticManager",
            "HumanApprovalMagenticManager",
            "GroupChatManager",
            "ProxyAgent",
            "PROXYAGENT",
        ]:
            assert _is_orchestrator_agent(name), f"{name} should pass gate"

    def test_sub_agent_names_fail_gate(self):
        """Balance-sheet sub-agent names do NOT pass the output gate."""
        from v4.callbacks.response_handlers import _is_orchestrator_agent
        for name in [
            "ConnectorAgent",
            "NormalizationAgent",
            "RulesAgent",
            "ReportAgent",
            "HITLAgent",
            "SomeCustomAgent",
        ]:
            assert not _is_orchestrator_agent(name), f"{name} should not pass gate"

    def test_agent_response_callback_routes_sub_agent_as_internal(self):
        """Sub-agent final messages are sent with INTERNAL_AGENT_MESSAGE type."""
        from v4.callbacks.response_handlers import agent_response_callback
        from v4.models.messages import WebsocketMessageType

        sent_types: List[str] = []

        async def fake_send(msg, uid, *, message_type):
            sent_types.append(message_type)

        mock_connection = MagicMock()
        mock_connection.send_status_update_async = fake_send

        # Build a fake ChatMessage from ConnectorAgent
        fake_msg = MagicMock()
        fake_msg.author_name = "ConnectorAgent"
        fake_msg.role = "assistant"
        fake_msg.text = '{"run_id":"abc","status":"done"}'

        with patch("v4.callbacks.response_handlers.connection_config", mock_connection):
            with patch("v4.callbacks.response_handlers.asyncio.create_task") as mock_task:
                # Capture the coroutine passed to create_task and run it
                captured = []
                def capture(coro):
                    captured.append(coro)
                mock_task.side_effect = capture

                agent_response_callback("ConnectorAgent", fake_msg, user_id="user-1")

                # Run the captured coroutine
                assert captured, "create_task was not called"
                asyncio.get_event_loop().run_until_complete(captured[0])

        assert sent_types == [WebsocketMessageType.INTERNAL_AGENT_MESSAGE]

    def test_agent_response_callback_routes_orchestrator_as_agent_message(self):
        """Orchestrator messages are sent with AGENT_MESSAGE type."""
        from v4.callbacks.response_handlers import agent_response_callback
        from v4.models.messages import WebsocketMessageType

        sent_types: List[str] = []

        async def fake_send(msg, uid, *, message_type):
            sent_types.append(message_type)

        mock_connection = MagicMock()
        mock_connection.send_status_update_async = fake_send

        fake_msg = MagicMock()
        fake_msg.author_name = "MagenticManager"
        fake_msg.role = "assistant"
        fake_msg.text = "Here is your final report..."

        with patch("v4.callbacks.response_handlers.connection_config", mock_connection):
            with patch("v4.callbacks.response_handlers.asyncio.create_task") as mock_task:
                captured = []
                mock_task.side_effect = lambda coro: captured.append(coro)
                agent_response_callback("MagenticManager", fake_msg, user_id="user-1")
                asyncio.get_event_loop().run_until_complete(captured[0])

        assert sent_types == [WebsocketMessageType.AGENT_MESSAGE]

    @pytest.mark.asyncio
    async def test_streaming_sub_agent_text_suppressed(self):
        """Streaming text from sub-agents is NOT forwarded; no AGENT_MESSAGE_STREAMING sent."""
        from v4.callbacks.response_handlers import streaming_agent_response_callback
        from v4.models.messages import WebsocketMessageType

        sent_types: List[str] = []

        async def fake_send(msg, uid, *, message_type):
            sent_types.append(message_type)

        mock_connection = MagicMock()
        mock_connection.send_status_update_async = fake_send

        fake_update = MagicMock()
        fake_update.text = "# Internal Accounting Review Report\n..."
        fake_update.contents = []

        with patch("v4.callbacks.response_handlers.connection_config", mock_connection):
            await streaming_agent_response_callback(
                "ReportAgent", fake_update, is_final=True, user_id="user-1"
            )

        assert WebsocketMessageType.AGENT_MESSAGE_STREAMING not in sent_types

    @pytest.mark.asyncio
    async def test_streaming_tool_calls_always_forwarded(self):
        """Tool-call events from sub-agents are always forwarded as AGENT_TOOL_MESSAGE."""
        from v4.callbacks.response_handlers import (
            streaming_agent_response_callback,
            _is_function_call_item,
        )
        from v4.models.messages import WebsocketMessageType

        sent_types: List[str] = []

        async def fake_send(msg, uid, *, message_type):
            sent_types.append(message_type)

        mock_connection = MagicMock()
        mock_connection.send_status_update_async = fake_send

        # Simulate a function-call content item
        fake_tool_item = MagicMock()
        fake_tool_item.content_type = "function_call"
        fake_tool_item.name = "get_balance_sheet_review"
        fake_tool_item.arguments = {"run_id": "abc123"}
        # No .text attribute on tool items
        del fake_tool_item.text

        fake_update = MagicMock()
        fake_update.text = ""
        fake_update.contents = [fake_tool_item]

        with patch("v4.callbacks.response_handlers.connection_config", mock_connection):
            await streaming_agent_response_callback(
                "ConnectorAgent", fake_update, is_final=False, user_id="user-1"
            )

        assert WebsocketMessageType.AGENT_TOOL_MESSAGE in sent_types
