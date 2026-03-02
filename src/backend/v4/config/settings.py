"""
Configuration settings for the Magentic Employee Onboarding system.
Handles Azure OpenAI, MCP, and environment setup (agent_framework version).
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set

from common.config.app_config import config
from common.models.messages_af import TeamConfiguration
from common.telemetry import current_trace_id, current_traceparent
from fastapi import WebSocket
from starlette.websockets import WebSocketState

# agent_framework substitutes
from agent_framework.azure import AzureOpenAIChatClient
# from agent_framework_azure_ai import AzureOpenAIChatClient
from agent_framework import ChatOptions

from v4.models.messages import MPlan, WebsocketMessageType

logger = logging.getLogger(__name__)


class AzureConfig:
    """Azure OpenAI and authentication configuration (agent_framework)."""

    def __init__(self):
        self.endpoint = config.AZURE_OPENAI_ENDPOINT
        self.reasoning_model = config.REASONING_MODEL_NAME
        self.standard_model = config.AZURE_OPENAI_DEPLOYMENT_NAME
        # self.bing_connection_name = config.AZURE_BING_CONNECTION_NAME

        # Acquire credential (assumes app_config wrapper returns a DefaultAzureCredential or similar)
        self.credential = config.get_azure_credentials()

    def ad_token_provider(self) -> str:
        """Return a bearer token string for Azure Cognitive Services scope."""
        token = self.credential.get_token(config.AZURE_COGNITIVE_SERVICES)
        return token.token

    async def create_chat_completion_service(self, use_reasoning_model: bool = False) -> AzureOpenAIChatClient:
        """
        Create an AzureOpenAIChatClient (agent_framework) for the selected model.
        Matches former AzureChatCompletion usage.
        """
        model_name = self.reasoning_model if use_reasoning_model else self.standard_model
        return AzureOpenAIChatClient(
            endpoint=self.endpoint,
            model_deployment_name=model_name,
            azure_ad_token_provider=self.ad_token_provider,  # function returning token string
        )

    def create_execution_settings(self) -> ChatOptions:
        """
        Create ChatOptions analogous to previous OpenAIChatPromptExecutionSettings.
        """
        return ChatOptions(
            max_output_tokens=4000,
            temperature=0.1,
        )


class MCPConfig:
    """MCP server configuration."""

    def __init__(self):
        self.url = config.MCP_SERVER_ENDPOINT
        self.name = config.MCP_SERVER_NAME
        self.description = config.MCP_SERVER_DESCRIPTION
        logger.info(f"🔧 MCP Config initialized - URL: {self.url}, Name: {self.name}")

    def get_headers(self, token: str):
        """Get MCP headers with authentication token."""
        headers = (
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            if token
            else {}
        )
        logger.debug(f"📋 MCP Headers created: {headers}")
        return headers


class OrchestrationConfig:
    """Configuration for orchestration settings (agent_framework workflow storage)."""

    def __init__(self):
        # Previously Dict[str, MagenticOrchestration]; now generic workflow objects from MagenticBuilder.build()
        self.orchestrations: Dict[str, Any] = {}  # user_id -> workflow instance
        self.agent_wrappers: Dict[str, list[Any]] = {}  # user_id -> wrapper instances
        self.workflow_session_ids: Dict[str, str] = {}  # user_id -> active conversation session_id
        self.plans: Dict[str, MPlan] = {}  # plan_id -> plan details
        self.approvals: Dict[str, bool] = {}  # m_plan_id -> approval status (None pending)
        self.sockets: Dict[str, WebSocket] = {}  # user_id -> WebSocket
        self.clarifications: Dict[str, str] = {}  # m_plan_id -> clarification response
        self.max_rounds: int = 20  # Maximum replanning rounds
        self.user_auth_tokens: Dict[str, str] = {}  # user_id -> latest bearer/id token
        self.workflow_last_run_context: Dict[str, Dict[str, str]] = {}  # user_id -> {"run_id", "session_id", "initial_goal"}

        # Event-driven notification system for approvals and clarifications
        self._approval_events: Dict[str, asyncio.Event] = {}
        self._clarification_events: Dict[str, asyncio.Event] = {}

        # Default timeout (seconds) for waiting operations
        self.default_timeout: float = 300.0

    def get_current_orchestration(self, user_id: str) -> Any:
        """Get existing orchestration workflow instance for user_id."""
        return self.orchestrations.get(user_id, None)

    def set_user_auth_token(self, user_id: str, token: str | None) -> bool:
        """Store latest user auth token. Returns True when token value changed."""
        if not user_id:
            return False

        normalized = str(token or "").strip()
        previous = self.user_auth_tokens.get(user_id, "")

        if normalized:
            self.user_auth_tokens[user_id] = normalized
        else:
            self.user_auth_tokens.pop(user_id, None)

        return previous != normalized

    def get_user_auth_token(self, user_id: str) -> str | None:
        if not user_id:
            return None
        token = str(self.user_auth_tokens.get(user_id, "")).strip()
        return token or None

    def set_approval_pending(self, plan_id: str) -> None:
        """Mark approval pending and create/reset its event."""
        self.approvals[plan_id] = None
        if plan_id not in self._approval_events:
            self._approval_events[plan_id] = asyncio.Event()
        else:
            self._approval_events[plan_id].clear()

    def set_approval_result(self, plan_id: str, approved: bool) -> None:
        """Set approval decision and trigger its event."""
        self.approvals[plan_id] = approved
        if plan_id in self._approval_events:
            self._approval_events[plan_id].set()

    async def wait_for_approval(self, plan_id: str, timeout: Optional[float] = None) -> bool:
        """
        Wait for an approval decision with timeout.

        Args:
            plan_id: The plan ID to wait for
            timeout: Timeout in seconds (defaults to default_timeout)

        Returns:
            The approval decision (True/False)

        Raises:
            asyncio.TimeoutError: If timeout is exceeded
            KeyError: If plan_id is not found in approvals
        """
        logger.info(f"Waiting for approval: {plan_id}")
        if timeout is None:
            timeout = self.default_timeout

        if plan_id not in self.approvals:
            raise KeyError(f"Plan ID {plan_id} not found in approvals")

        # Already decided
        if self.approvals[plan_id] is not None:
            return self.approvals[plan_id]

        if plan_id not in self._approval_events:
            self._approval_events[plan_id] = asyncio.Event()

        try:
            await asyncio.wait_for(self._approval_events[plan_id].wait(), timeout=timeout)
            logger.info(f"Approval received: {plan_id}")
            return self.approvals[plan_id]
        except asyncio.TimeoutError:
            # Clean up on timeout
            logger.warning(f"Approval timeout: {plan_id}")
            self.cleanup_approval(plan_id)
            raise
        except asyncio.CancelledError:
            logger.debug("Approval request %s was cancelled", plan_id)
            raise
        except Exception as e:
            logger.error("Unexpected error waiting for approval %s: %s", plan_id, e)
            raise
        finally:
            if plan_id in self.approvals and self.approvals[plan_id] is None:
                self.cleanup_approval(plan_id)

    def set_clarification_pending(self, request_id: str) -> None:
        """Mark clarification pending and create/reset its event."""
        self.clarifications[request_id] = None
        if request_id not in self._clarification_events:
            self._clarification_events[request_id] = asyncio.Event()
        else:
            self._clarification_events[request_id].clear()

    def set_clarification_result(self, request_id: str, answer: str) -> None:
        """Set clarification answer and trigger event."""
        self.clarifications[request_id] = answer
        if request_id in self._clarification_events:
            self._clarification_events[request_id].set()

    async def wait_for_clarification(self, request_id: str, timeout: Optional[float] = None) -> str:
        """Wait for clarification response with timeout."""
        if timeout is None:
            timeout = self.default_timeout

        if request_id not in self.clarifications:
            raise KeyError(f"Request ID {request_id} not found in clarifications")

        if self.clarifications[request_id] is not None:
            return self.clarifications[request_id]

        if request_id not in self._clarification_events:
            self._clarification_events[request_id] = asyncio.Event()

        try:
            await asyncio.wait_for(self._clarification_events[request_id].wait(), timeout=timeout)
            return self.clarifications[request_id]
        except asyncio.TimeoutError:
            self.cleanup_clarification(request_id)
            raise
        except asyncio.CancelledError:
            logger.debug("Clarification request %s was cancelled", request_id)
            raise
        except Exception as e:
            logger.error("Unexpected error waiting for clarification %s: %s", request_id, e)
            raise
        finally:
            if request_id in self.clarifications and self.clarifications[request_id] is None:
                self.cleanup_clarification(request_id)

    def cleanup_approval(self, plan_id: str) -> None:
        """Remove approval tracking data and event."""
        self.approvals.pop(plan_id, None)
        self._approval_events.pop(plan_id, None)

    def cleanup_clarification(self, request_id: str) -> None:
        """Remove clarification tracking data and event."""
        self.clarifications.pop(request_id, None)
        self._clarification_events.pop(request_id, None)


@dataclass
class ActiveRunState:
    run_id: str
    plan_id: str
    user_id: str
    session_id: str
    process_id: str
    started_at: str
    expires_at: str


class RunControlConfig:
    """Tracks one active workflow execution per user with TTL auto-release."""

    def __init__(self):
        self._runs_by_user: Dict[str, ActiveRunState] = {}
        self._tasks_by_run: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self.ttl_seconds = int(
            os.getenv("ORCHESTRATION_RUN_TTL_SECONDS", "1800").strip() or "1800"
        )

    async def acquire_run(
        self,
        *,
        user_id: str,
        session_id: str,
        run_id: str,
        plan_id: str,
        process_id: str | None = None,
    ) -> tuple[bool, ActiveRunState]:
        if not user_id:
            raise ValueError("user_id is required")
        async with self._lock:
            self._cleanup_expired_locked()
            existing = self._runs_by_user.get(user_id)
            if existing:
                return False, existing

            now = datetime.now(timezone.utc)
            state = ActiveRunState(
                run_id=run_id,
                plan_id=plan_id,
                user_id=user_id,
                session_id=session_id,
                process_id=process_id or plan_id,
                started_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            )
            self._runs_by_user[user_id] = state
            return True, state

    async def get_active_run(self, user_id: str) -> ActiveRunState | None:
        if not user_id:
            return None
        async with self._lock:
            self._cleanup_expired_locked()
            return self._runs_by_user.get(user_id)

    async def release_run(self, user_id: str, run_id: str | None = None) -> None:
        if not user_id:
            return
        async with self._lock:
            existing = self._runs_by_user.get(user_id)
            if not existing:
                return
            if run_id and existing.run_id != run_id:
                return
            self._tasks_by_run.pop(existing.run_id, None)
            self._runs_by_user.pop(user_id, None)

    async def refresh_ttl(self, user_id: str, run_id: str) -> None:
        async with self._lock:
            existing = self._runs_by_user.get(user_id)
            if not existing or existing.run_id != run_id:
                return
            now = datetime.now(timezone.utc)
            existing.expires_at = (now + timedelta(seconds=self.ttl_seconds)).isoformat()

    async def register_task(self, *, user_id: str, run_id: str, task: asyncio.Task) -> None:
        if not user_id:
            return
        async with self._lock:
            existing = self._runs_by_user.get(user_id)
            if not existing or existing.run_id != run_id:
                return
            self._tasks_by_run[run_id] = task

    async def cancel_run(
        self, *, user_id: str, run_id: str | None = None
    ) -> tuple[bool, ActiveRunState | None, bool]:
        task_to_cancel: asyncio.Task | None = None

        async with self._lock:
            self._cleanup_expired_locked()
            existing = self._runs_by_user.get(user_id)
            if not existing:
                return False, None, False
            if run_id and existing.run_id != run_id:
                return False, existing, False

            task_to_cancel = self._tasks_by_run.pop(existing.run_id, None)
            self._runs_by_user.pop(user_id, None)

        task_cancel_requested = False
        if task_to_cancel and not task_to_cancel.done():
            task_to_cancel.cancel()
            task_cancel_requested = True

        return True, existing, task_cancel_requested

    def _cleanup_expired_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired_users = []
        for user_id, state in self._runs_by_user.items():
            try:
                expires_at = datetime.fromisoformat(state.expires_at)
            except ValueError:
                expired_users.append(user_id)
                continue
            if expires_at <= now:
                expired_users.append(user_id)
        for user_id in expired_users:
            state = self._runs_by_user.pop(user_id, None)
            if state:
                self._tasks_by_run.pop(state.run_id, None)


class ConnectionConfig:
    """Connection manager for WebSocket connections."""

    def __init__(self):
        self.connections: Dict[str, Set[WebSocket]] = {}
        self.user_to_processes: Dict[str, Set[str]] = {}

    def add_connection(self, process_id: str, connection: WebSocket, user_id: str | None = None):
        """Add a connection for a process/user without dropping existing connections."""
        process_id = str(process_id)
        self.connections.setdefault(process_id, set()).add(connection)
        if user_id:
            user_id = str(user_id)
            self.user_to_processes.setdefault(user_id, set()).add(process_id)
            logger.info(
                "WebSocket connection added process=%s user=%s total_process_sockets=%d",
                process_id,
                user_id,
                len(self.connections.get(process_id, set())),
            )
        else:
            logger.info("WebSocket connection added process=%s", process_id)

    def remove_connection(self, process_id: str, connection: WebSocket | None = None):
        """Remove one or all connections for a process and clean user mappings."""
        process_id = str(process_id)
        socket_set = self.connections.get(process_id)
        if not socket_set:
            return

        if connection is not None:
            socket_set.discard(connection)

        if connection is None or not socket_set:
            self.connections.pop(process_id, None)
            for user_id, processes in list(self.user_to_processes.items()):
                if process_id in processes:
                    processes.discard(process_id)
                if not processes:
                    self.user_to_processes.pop(user_id, None)

    def get_connections(self, process_id: str) -> Set[WebSocket]:
        """Fetch active sockets by process_id."""
        return set(self.connections.get(str(process_id), set()))

    async def close_connection(self, process_id: str, connection: WebSocket | None = None):
        """Close one or all sockets by process_id."""
        process_id = str(process_id)
        sockets = (
            {connection}
            if connection is not None
            else set(self.connections.get(process_id, set()))
        )
        if not sockets:
            logger.debug("No connection found for process_id=%s", process_id)
            self.remove_connection(process_id, connection=connection)
            return

        for ws in sockets:
            try:
                if ws.client_state != WebSocketState.DISCONNECTED:
                    await ws.close()
            except Exception as exc:
                logger.debug("Error closing websocket process=%s: %s", process_id, exc)
            finally:
                self.remove_connection(process_id, connection=ws)

    async def send_status_update_async(
        self,
        message: Any,
        user_id: str,
        message_type: WebsocketMessageType = WebsocketMessageType.SYSTEM_MESSAGE,
    ):
        """Send a status update to all active user sockets."""
        if not user_id:
            logger.warning("No user_id provided for WebSocket message")
            return

        try:
            if hasattr(message, "to_dict"):
                message_data = message.to_dict()
            elif hasattr(message, "data") and hasattr(message, "type"):
                message_data = message.data
            elif isinstance(message, dict):
                message_data = message
            else:
                message_data = str(message)
        except Exception as e:
            logger.error("Error processing message data: %s", e)
            message_data = str(message)

        process_ids = set(self.user_to_processes.get(user_id, set()))
        if not process_ids and isinstance(message_data, dict):
            process_fallback = str(
                message_data.get("process_id") or message_data.get("plan_id") or ""
            ).strip()
            if process_fallback and process_fallback in self.connections:
                process_ids.add(process_fallback)
                logger.info(
                    "Using process-id fallback for websocket delivery user=%s process=%s",
                    user_id,
                    process_fallback,
                )

        if not process_ids:
            logger.warning("No active WebSocket process found for user ID: %s", user_id)
            logger.debug("Available user mappings: %s", list(self.user_to_processes.keys()))
            return

        payload = {
            "type": message_type,
            "data": message_data,
            "meta": {
                "trace_id": current_trace_id(),
                "traceparent": current_traceparent(),
            },
        }

        stale_processes: set[str] = set()
        for process_id in list(process_ids):
            process_sockets = self.get_connections(process_id)
            if not process_sockets:
                stale_processes.add(process_id)
                continue
            for ws in process_sockets:
                try:
                    await ws.send_text(json.dumps(payload, default=str))
                except Exception as exc:
                    logger.warning(
                        "Failed to send websocket message user=%s process=%s: %s",
                        user_id,
                        process_id,
                        exc,
                    )
                    self.remove_connection(process_id, connection=ws)

        for process_id in stale_processes:
            self.remove_connection(process_id)

    def send_status_update(self, message: str, process_id: str):
        """Sync helper to send a message by process_id."""
        process_id = str(process_id)
        for connection in self.get_connections(process_id):
            try:
                asyncio.create_task(connection.send_text(message))
            except Exception as e:
                logger.error("Failed to send message to process %s: %s", process_id, e)


class TeamConfig:
    """Team configuration for agents."""

    def __init__(self):
        self.teams: Dict[str, TeamConfiguration] = {}

    def set_current_team(self, user_id: str, team_configuration: TeamConfiguration):
        """Store current team configuration for user."""
        self.teams[user_id] = team_configuration

    def get_current_team(self, user_id: str) -> TeamConfiguration:
        """Retrieve current team configuration for user."""
        return self.teams.get(user_id, None)


# Global config instances (names unchanged)
azure_config = AzureConfig()
mcp_config = MCPConfig()
orchestration_config = OrchestrationConfig()
run_control_config = RunControlConfig()
connection_config = ConnectionConfig()
team_config = TeamConfig()
