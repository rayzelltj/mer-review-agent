"""
Enhanced response callbacks (agent_framework version) for employee onboarding agent system.
"""

import asyncio
import logging
import time
import re
from typing import Any

from agent_framework import ChatMessage
# Removed: from agent_framework._content import FunctionCallContent  (does not exist)

try:
    from agent_framework._workflows._magentic import AgentRunResponseUpdate  # Streaming update type from workflows
except ImportError:  # Older/newer local package version — fall back to Any for the type hint
    from typing import Any as AgentRunResponseUpdate  # type: ignore[assignment]

from v4.config.settings import connection_config
from v4.models.messages import (
    AgentMessage,
    AgentMessageStreaming,
    AgentToolCall,
    AgentToolMessage,
    WebsocketMessageType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single-writer output gate
# ---------------------------------------------------------------------------
# ONLY agents whose name appears in this set are allowed to emit
# WebsocketMessageType.AGENT_MESSAGE / AGENT_MESSAGE_STREAMING to the UI.
# All other agents are re-typed as INTERNAL_AGENT_MESSAGE so the frontend
# (and any logging middleware) can distinguish orchestrator output from
# intermediate agent chatter without dropping the data.
#
# Add the exact agent_name string as it appears in the team JSON / ChatAgent
# constructor.  The comparison is case-insensitive.
#
# Sub-agents (ConnectorAgent, NormalizationAgent, RulesAgent, ReportAgent,
# HITLAgent) are intentionally excluded: they must return structured JSON
# to the orchestrator, not prose to the end-user.
ORCHESTRATOR_AGENT_NAMES: frozenset[str] = frozenset(
    {
        "magenticmanager",
        "magentic_manager",       # agent_framework MAGENTIC_MANAGER_NAME constant
        "standardmagenticmanager",
        "humanapprovalmagenticmanager",
        "groupchatmanager",
        "proxyagent",         # ProxyAgent relays the user-facing summary
    }
)

# Internal names that must never appear in user-facing message text.
_INTERNAL_NAME_MAP: dict[str, str] = {
    "ConnectorAgent": "Data Connector",
    "NormalizationAgent": "Data Processor",
    "RulesAgent": "Rules Engine",
    "ReportAgent": "Report Generator",
    "HITLAgent": "Evidence Collector",
    "ReviewAgent": "Review Pipeline",
    "MagenticManager": "Assistant",
    "HumanApprovalMagenticManager": "Assistant",
    "ProxyAgent": "Assistant",
}

# Compiled once for efficiency.
_INTERNAL_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _INTERNAL_NAME_MAP) + r")\b"
)


def sanitize_for_display(text: str) -> str:
    """Replace internal agent/tool names with user-friendly equivalents.

    This is a best-effort sanitizer. It catches the most common leakage patterns
    (agent names used as nouns in prose) without risking false positives on
    unrelated content.
    """
    if not text:
        return text
    return _INTERNAL_NAME_RE.sub(lambda m: _INTERNAL_NAME_MAP[m.group(0)], text)


def _is_orchestrator_agent(agent_name: str) -> bool:
    """Return True if this agent is allowed to emit visible messages to the UI."""
    return agent_name.strip().lower() in ORCHESTRATOR_AGENT_NAMES


def clean_citations(text: str) -> str:
    """Remove citation markers from agent responses while preserving formatting."""
    if not text:
        return text
    text = re.sub(r'\[\d+:\d+\|source\]', '', text)
    text = re.sub(r'\[\s*source\s*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'【[^】]*】', '', text)
    text = re.sub(r'\(source:[^)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[source:[^\]]*\]', '', text, flags=re.IGNORECASE)
    return text


def _is_function_call_item(item: Any) -> bool:
    """Heuristic to detect a function/tool call item without relying on SK class types."""
    if item is None:
        return False
    # Common SK attributes: content_type == "function_call"
    if getattr(item, "content_type", None) == "function_call":
        return True
    # Agent framework may surface something with name & arguments but no text
    if hasattr(item, "name") and hasattr(item, "arguments") and not hasattr(item, "text"):
        return True
    return False


def _extract_tool_calls_from_contents(contents: list[Any]) -> list[AgentToolCall]:
    """Convert function/tool call-like items into AgentToolCall objects via duck typing."""
    tool_calls: list[AgentToolCall] = []
    for item in contents:
        if _is_function_call_item(item):
            tool_calls.append(
                AgentToolCall(
                    tool_name=getattr(item, "name", "unknown_tool"),
                    arguments=getattr(item, "arguments", {}) or {},
                )
            )
    return tool_calls


async def agent_response_callback(
    agent_id: str,
    message: ChatMessage,
    user_id: str | None = None,
) -> None:
    """
    Final (non-streaming) agent response callback using agent_framework ChatMessage.

    Output gate: only orchestrator agents emit WebsocketMessageType.AGENT_MESSAGE.
    All other agents are emitted as INTERNAL_AGENT_MESSAGE so the UI can suppress
    them, while the raw text is still logged and available for debugging.
    """
    agent_name = getattr(message, "author_name", None) or agent_id or "Unknown Agent"
    role = getattr(message, "role", "assistant")

    # ChatMessage has a .text property that concatenates all TextContent items
    text = ""
    if isinstance(message, ChatMessage):
        text = message.text
    else:
        text = str(getattr(message, "text", ""))

    text = sanitize_for_display(clean_citations(text or ""))

    if not user_id:
        logger.debug("No user_id provided; skipping websocket send for final message.")
        return

    # ----- Output gate -----
    is_orchestrator = _is_orchestrator_agent(agent_name)
    ws_type = (
        WebsocketMessageType.AGENT_MESSAGE
        if is_orchestrator
        else WebsocketMessageType.INTERNAL_AGENT_MESSAGE
    )
    if not is_orchestrator:
        logger.debug(
            "output_gate: routing %s message as INTERNAL_AGENT_MESSAGE (len=%d)",
            agent_name,
            len(text),
        )

    try:
        final_message = AgentMessage(
            agent_name=agent_name,
            timestamp=time.time(),
            content=text,
        )
        await connection_config.send_status_update_async(
            final_message,
            user_id,
            message_type=ws_type,
        )
        logger.info("%s message (agent=%s type=%s): %s", str(role).capitalize(), agent_name, ws_type, text[:200])
    except Exception as e:
        logger.error("agent_response_callback error sending WebSocket message: %s", e)


async def streaming_agent_response_callback(
    agent_id: str,
    update: AgentRunResponseUpdate,
    is_final: bool,
    user_id: str | None = None,
) -> None:
    """
    Streaming callback for incremental agent output (AgentRunResponseUpdate).

    Output gate: only orchestrator agents emit AGENT_MESSAGE_STREAMING.
    Sub-agents' streaming chunks are suppressed entirely (they must return
    structured JSON, not prose, so streaming chunks are noise).
    Tool-call events are always forwarded regardless of agent identity so the
    UI can display activity indicators.
    """
    if not user_id:
        return

    try:
        chunk_text = getattr(update, "text", None)
        if not chunk_text:
            contents = getattr(update, "contents", []) or []
            collected = []
            for item in contents:
                txt = getattr(item, "text", None)
                if txt:
                    collected.append(str(txt))
            chunk_text = "".join(collected) if collected else ""

        cleaned = sanitize_for_display(clean_citations(chunk_text or ""))

        # Tool-call messages: always forward (show spinner / activity) for ALL agents
        contents = getattr(update, "contents", []) or []
        tool_calls = _extract_tool_calls_from_contents(contents)
        if tool_calls:
            tool_message = AgentToolMessage(agent_name=agent_id)
            tool_message.tool_calls.extend(tool_calls)
            await connection_config.send_status_update_async(
                tool_message,
                user_id,
                message_type=WebsocketMessageType.AGENT_TOOL_MESSAGE,
            )
            logger.info("Tool calls streamed from %s: %d", agent_id, len(tool_calls))

        # Text streaming: gate to orchestrator agents only
        if cleaned and _is_orchestrator_agent(agent_id):
            streaming_payload = AgentMessageStreaming(
                agent_name=agent_id,
                content=cleaned,
                is_final=is_final,
            )
            await connection_config.send_status_update_async(
                streaming_payload,
                user_id,
                message_type=WebsocketMessageType.AGENT_MESSAGE_STREAMING,
            )
            logger.debug("Streaming chunk (agent=%s final=%s len=%d)", agent_id, is_final, len(cleaned))
        elif cleaned:
            logger.debug(
                "output_gate: suppressing streaming chunk from sub-agent %s (len=%d)",
                agent_id,
                len(cleaned),
            )
    except Exception as e:
        logger.error("streaming_agent_response_callback error: %s", e)
