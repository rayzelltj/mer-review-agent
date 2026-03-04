"""Orchestration manager (agent_framework version) handling multi-agent Magentic workflow creation and execution."""

import asyncio
import logging
import re
import time
from typing import List, Optional

# agent_framework imports
from agent_framework_azure_ai import AzureAIAgentClient
from agent_framework import (
    ChatMessage,
    WorkflowOutputEvent,
    MagenticBuilder,
    InMemoryCheckpointStorage,
    MagenticOrchestratorMessageEvent,
    MagenticAgentDeltaEvent,
    MagenticAgentMessageEvent,
    MagenticFinalResultEvent,
)

from common.config.app_config import config
from common.database.database_factory import DatabaseFactory
from common.database.conversation_store import (
    save_session_context,
    get_session_context,
)
from common.models.messages_af import PlanStatus, TeamConfiguration
from common.telemetry import traced_phase

from common.database.database_base import DatabaseBase

from v4.common.services.team_service import TeamService
from v4.callbacks.response_handlers import (
    agent_response_callback,
    streaming_agent_response_callback,
    sanitize_for_display,
    clean_citations,
)
from v4.config.settings import connection_config, orchestration_config, run_control_config
from v4.models.messages import WebsocketMessageType
from v4.orchestration.human_approval_manager import HumanApprovalMagenticManager
from v4.magentic_agents.magentic_agent_factory import MagenticAgentFactory


_RUN_ID_PATTERN = re.compile(
    r"""
    (?:Run\s*ID[:\s]+)                    # "Run ID: ..." or "Run ID ..."
    ([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})  # standard UUID
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Fallback: matches "run_id": "..." in JSON output the agent may reproduce verbatim
_RUN_ID_JSON_PATTERN = re.compile(
    r'"run_id"\s*:\s*"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})"',
    re.IGNORECASE,
)

# Capture client_id and period from "Balance sheet review complete for {client_id} period {period}"
_CLIENT_PERIOD_PATTERN = re.compile(
    r"(?:review\s+complete\s+for|review\s+for)\s+(\S+)\s+period\s+(\S+)",
    re.IGNORECASE,
)


def _try_capture_run_context(
    text: str, user_id: str, session_id: str, initial_goal: str
) -> None:
    """Extract a balance-sheet run_id from agent/tool output and cache it for follow-ups.

    Tries multiple patterns: the prose "Run ID: <uuid>" format emitted by MCP tools,
    and the JSON "run_id": "<uuid>" format from raw tool output. First match wins.
    Also captures client_id and period_end if present.
    """
    match = _RUN_ID_PATTERN.search(text) or _RUN_ID_JSON_PATTERN.search(text)
    if match:
        captured = match.group(1)
        existing = orchestration_config.workflow_last_run_context.get(user_id) or {}
        ctx: dict[str, str] = {
            "run_id": captured,
            "session_id": session_id,
            "initial_goal": initial_goal,
        }
        # Try to capture client_id and period from tool output
        cp_match = _CLIENT_PERIOD_PATTERN.search(text)
        if cp_match:
            ctx["client_id"] = cp_match.group(1)
            ctx["period_end"] = cp_match.group(2).rstrip(".")
        # Preserve any existing review_summary if not overwriting
        if "review_summary" in existing and existing.get("run_id") == captured:
            ctx["review_summary"] = existing["review_summary"]
        orchestration_config.workflow_last_run_context[user_id] = ctx
        OrchestrationManager.logger.info(
            "Captured run context run_id=%s client=%s period=%s session=%s user=%s",
            captured,
            ctx.get("client_id", "?"),
            ctx.get("period_end", "?"),
            session_id,
            user_id,
        )


def _capture_review_summary(final_text: str, user_id: str) -> None:
    """Store a condensed version of the final review output for follow-up context.

    Persists both in-memory (for fast same-container follow-ups) and to Cosmos
    (for cross-restart durability). The Cosmos write is fire-and-forget.
    """
    if not final_text or len(final_text) < 100:
        return
    existing = orchestration_config.workflow_last_run_context.get(user_id)
    if not existing or not existing.get("run_id"):
        return
    # Store up to 6000 chars of the final answer as review summary context.
    # This gives the agent enough data to answer most follow-ups directly.
    summary = final_text[:6000]
    existing["review_summary"] = summary
    orchestration_config.workflow_last_run_context[user_id] = existing
    OrchestrationManager.logger.info(
        "Stored review summary (%d chars) for user=%s run_id=%s",
        len(summary),
        user_id,
        existing.get("run_id", "?"),
    )
    # Persist to Cosmos for cross-restart durability
    try:
        save_session_context(
            user_id=user_id,
            session_id=existing.get("session_id", ""),
            run_id=existing.get("run_id", ""),
            initial_goal=existing.get("initial_goal", ""),
            client_id=existing.get("client_id", ""),
            period_end=existing.get("period_end", ""),
            review_summary=summary,
        )
    except Exception:
        OrchestrationManager.logger.warning(
            "Failed to persist session context to Cosmos for user=%s", user_id,
            exc_info=True,
        )


class OrchestrationManager:
    """Manager for handling orchestration logic using agent_framework Magentic workflow."""

    logger = logging.getLogger(f"{__name__}.OrchestrationManager")

    def __init__(self):
        self.user_id: Optional[str] = None
        self.logger = self.__class__.logger

    # ---------------------------
    # Orchestration construction
    # ---------------------------
    @classmethod
    async def init_orchestration(
        cls,
        agents: List,
        team_config: TeamConfiguration,
        memory_store: DatabaseBase,
        user_id: str | None = None,
    ):
        """
        Initialize a Magentic workflow with:
          - Provided agents (participants)
          - HumanApprovalMagenticManager as orchestrator manager
          - AzureAIAgentClient as the underlying chat client
          - Event-based callbacks for streaming and final responses
        - Uses same deployment, endpoint, and credentials
        - Applies same execution settings (temperature, max_tokens)
        - Maintains same human approval workflow
        """
        if not user_id:
            raise ValueError("user_id is required to initialize orchestration")

        # Get credential from config (same as old version)
        credential = config.get_azure_credential(client_id=config.AZURE_CLIENT_ID)

        # Create Azure AI Agent client for orchestration using config
        # This replaces AzureChatCompletion from SK
        agent_name = team_config.name if team_config.name else "OrchestratorAgent"

        try:
            chat_client = AzureAIAgentClient(
                project_endpoint=config.AZURE_AI_PROJECT_ENDPOINT,
                model_deployment_name=team_config.deployment_name,
                agent_name=agent_name,
                async_credential=credential,
            )

            cls.logger.info(
                "Created AzureAIAgentClient for orchestration with model '%s' at endpoint '%s'",
                team_config.deployment_name,
                config.AZURE_AI_PROJECT_ENDPOINT,
            )
        except Exception as e:
            cls.logger.error("Failed to create AzureAIAgentClient: %s", e)
            raise

        # Create HumanApprovalMagenticManager with the chat client
        # Execution settings (temperature=0.1, max_tokens=4000) are configured via
        # orchestration_config.create_execution_settings() which matches old SK version
        try:
            manager = HumanApprovalMagenticManager(
                user_id=user_id,
                chat_client=chat_client,
                instructions=None,  # Orchestrator system instructions (optional)
                max_round_count=orchestration_config.max_rounds,
            )
            cls.logger.info(
                "Created HumanApprovalMagenticManager for user '%s' with max_rounds=%d",
                user_id,
                orchestration_config.max_rounds,
            )
        except Exception as e:
            cls.logger.error("Failed to create manager: %s", e)
            raise

        # Build participant map: use each agent's name as key
        participants = {}
        for ag in agents:
            name = getattr(ag, "agent_name", None) or getattr(ag, "name", None)
            if not name:
                name = f"agent_{len(participants) + 1}"

            # Extract the inner ChatAgent for wrapper templates
            # FoundryAgentTemplate wrap a ChatAgent in self._agent
            # ProxyAgent directly extends BaseAgent and can be used as-is
            if hasattr(ag, "_agent") and ag._agent is not None:
                # This is a wrapper (FoundryAgentTemplate)
                # Use the inner ChatAgent which implements AgentProtocol
                participants[name] = ag._agent
                cls.logger.debug("Added participant '%s' (extracted inner agent)", name)
            else:
                # This is already an agent (like ProxyAgent extending BaseAgent)
                participants[name] = ag
                cls.logger.debug("Added participant '%s'", name)

        # Assemble workflow with callback
        storage = InMemoryCheckpointStorage()
        builder = (
            MagenticBuilder()
            .participants(**participants)
            .with_standard_manager(
                manager=manager,
                max_round_count=orchestration_config.max_rounds,
                max_stall_count=3,
            )
            .with_checkpointing(storage)
        )

        # Build workflow
        workflow = builder.build()
        cls.logger.info(
            "Built Magentic workflow with %d participants and event callbacks",
            len(participants),
        )

        return workflow

    # ---------------------------
    # Orchestration retrieval
    # ---------------------------
    @classmethod
    async def get_current_or_new_orchestration(
        cls,
        user_id: str,
        team_config: TeamConfiguration,
        team_switched: bool,
        team_service: TeamService = None,
    ):
        """
        Return an existing workflow for the user or create a new one if:
          - None exists
          - Team switched flag is True
        """
        current = orchestration_config.get_current_orchestration(user_id)
        if current is None or team_switched:
            orchestration_config.workflow_session_ids.pop(user_id, None)
            existing_wrappers = orchestration_config.agent_wrappers.pop(user_id, [])
            for wrapper in existing_wrappers:
                close_coro = getattr(wrapper, "close", None)
                if callable(close_coro):
                    try:
                        await close_coro()
                    except Exception as e:
                        cls.logger.warning(
                            "Error closing prior wrapper agent for user '%s': %s",
                            user_id,
                            e,
                        )

            if current is not None and team_switched:
                cls.logger.info(
                    "Team switched, closing previous agents for user '%s'", user_id
                )
                # Close prior agents (same logic as old version)
                for agent in getattr(current, "_participants", {}).values():
                    agent_name = getattr(
                        agent, "agent_name", getattr(agent, "name", "")
                    )
                    if agent_name != "ProxyAgent":
                        close_coro = getattr(agent, "close", None)
                        if callable(close_coro):
                            try:
                                await close_coro()
                                cls.logger.debug("Closed agent '%s'", agent_name)
                            except Exception as e:
                                cls.logger.error("Error closing agent: %s", e)

            factory = MagenticAgentFactory(team_service=team_service)
            try:
                user_auth_token = orchestration_config.get_user_auth_token(user_id)
                with traced_phase(
                    "orchestration.team_assembly",
                    logger=cls.logger,
                    attributes={"user.id": user_id, "team.id": team_config.team_id},
                ):
                    agents = await factory.get_agents(
                        user_id=user_id,
                        team_config_input=team_config,
                        memory_store=team_service.memory_context,
                        user_auth_token=user_auth_token,
                    )
                cls.logger.info("Created %d agents for user '%s'", len(agents), user_id)
            except Exception as e:
                cls.logger.error(
                    "Failed to create agents for user '%s': %s", user_id, e
                )
                print(f"Failed to create agents for user '{user_id}': {e}")
                raise
            try:
                cls.logger.info("Initializing new orchestration for user '%s'", user_id)
                with traced_phase(
                    "orchestration.workflow_init",
                    logger=cls.logger,
                    attributes={"user.id": user_id, "team.id": team_config.team_id},
                ):
                    orchestration_config.orchestrations[user_id] = (
                        await cls.init_orchestration(
                            agents, team_config, team_service.memory_context, user_id
                        )
                    )
                    orchestration_config.agent_wrappers[user_id] = list(agents)
            except Exception as e:
                cls.logger.error(
                    "Failed to initialize orchestration for user '%s': %s", user_id, e
                )
                print(f"Failed to initialize orchestration for user '{user_id}': {e}")
                raise
        return orchestration_config.get_current_orchestration(user_id)

    # ---------------------------
    # Execution
    # ---------------------------
    async def run_orchestration(
        self,
        user_id: str,
        input_task,
        plan_id: str,
        run_id: str,
    ) -> None:
        """
        Execute the Magentic workflow for the provided user and task description.
        """
        self.logger.info(
            "Starting orchestration job run_id=%s plan_id=%s user=%s",
            run_id,
            plan_id,
            user_id,
        )

        workflow = orchestration_config.get_current_orchestration(user_id)
        if workflow is None:
            self.logger.warning(
                "Orchestration missing for user=%s; attempting lazy initialization.",
                user_id,
            )
            bootstrap_store = await DatabaseFactory.get_database(user_id=user_id)
            user_current_team = await bootstrap_store.get_current_team(user_id=user_id)
            if not user_current_team:
                raise ValueError("Orchestration not initialized and no current team is set.")

            team_service = TeamService(bootstrap_store)
            team_configuration = await team_service.get_team_configuration(
                user_current_team.team_id,
                user_id,
            )
            if not team_configuration:
                raise ValueError(
                    f"Unable to initialize orchestration. Team '{user_current_team.team_id}' not found."
                )

            workflow = await self.get_current_or_new_orchestration(
                user_id=user_id,
                team_config=team_configuration,
                team_switched=False,
                team_service=team_service,
            )
            if workflow is None:
                raise ValueError("Orchestration initialization failed for user.")
        session_id = str(getattr(input_task, "session_id", "") or "")
        previous_session_id = orchestration_config.workflow_session_ids.get(user_id)
        reset_executor_state = previous_session_id != session_id
        orchestration_config.workflow_session_ids[user_id] = session_id

        executors = getattr(workflow, "executors", {})
        self.logger.debug("Executor keys at run start: %s", list(executors.keys()))

        if reset_executor_state:
            with traced_phase(
                "orchestration.executor_reset",
                logger=self.logger,
                attributes={
                    "run.id": run_id,
                    "plan.id": plan_id,
                    "user.id": user_id,
                    "session.id": session_id,
                },
            ):
                for exec_key, executor in executors.items():
                    try:
                        if exec_key == "magentic_orchestrator":
                            if hasattr(executor, "_conversation"):
                                conv = getattr(executor, "_conversation")
                                if hasattr(conv, "clear") and callable(conv.clear):
                                    conv.clear()
                                elif isinstance(conv, list):
                                    conv[:] = []
                        else:
                            if hasattr(executor, "_chat_history"):
                                hist = getattr(executor, "_chat_history")
                                if hasattr(hist, "clear") and callable(hist.clear):
                                    hist.clear()
                                elif isinstance(hist, list):
                                    hist[:] = []
                    except Exception as e:
                        self.logger.warning(
                            "Failed clearing state for executor %s: %s", exec_key, e
                        )
        else:
            self.logger.info(
                "Continuing orchestration conversation in existing session user=%s session=%s run_id=%s",
                user_id,
                session_id,
                run_id,
            )

        # Build task from input (same as old version)
        task_text = getattr(input_task, "description", str(input_task))

        # Inject prior run context for follow-up questions in the same session
        if not reset_executor_state:
            prior_ctx = orchestration_config.workflow_last_run_context.get(user_id)
            # Fall back to Cosmos if in-memory context is empty (e.g. after restart)
            if (not prior_ctx or prior_ctx.get("session_id") != session_id) and session_id:
                cosmos_ctx = get_session_context(user_id, session_id)
                if cosmos_ctx and cosmos_ctx.get("run_id"):
                    prior_ctx = {
                        "run_id": cosmos_ctx["run_id"],
                        "session_id": cosmos_ctx.get("original_session_id", session_id),
                        "initial_goal": cosmos_ctx.get("initial_goal", ""),
                        "client_id": cosmos_ctx.get("client_id", ""),
                        "period_end": cosmos_ctx.get("period_end", ""),
                        "review_summary": cosmos_ctx.get("review_summary", ""),
                    }
                    # Re-hydrate in-memory cache
                    orchestration_config.workflow_last_run_context[user_id] = prior_ctx
                    self.logger.info(
                        "Re-hydrated session context from Cosmos user=%s session=%s run_id=%s",
                        user_id, session_id, prior_ctx["run_id"],
                    )
            if prior_ctx and prior_ctx.get("session_id") == session_id:
                prior_run_id = prior_ctx["run_id"]
                original_request = prior_ctx.get("initial_goal", "")
                prior_client_id = prior_ctx.get("client_id", "")
                prior_period = prior_ctx.get("period_end", "")
                review_summary = prior_ctx.get("review_summary", "")

                context_lines = [
                    "=== FOLLOW-UP CONTEXT (same session) ===",
                    "",
                    "PRIOR REVIEW DATA:",
                    f"- Balance sheet review run_id: {prior_run_id}",
                    f"- Original request: {original_request}",
                ]
                if prior_client_id:
                    context_lines.append(f"- Client ID (QBO realm): {prior_client_id}")
                if prior_period:
                    context_lines.append(f"- Period end date: {prior_period}")

                # Include conversation context from frontend (recent messages)
                conv_ctx = getattr(input_task, "conversation_context", None) or []
                if conv_ctx:
                    context_lines.append("")
                    context_lines.append("RECENT CONVERSATION HISTORY:")
                    for msg in conv_ctx[-8:]:  # Last 8 messages max
                        context_lines.append(f"  {msg}")

                # Include the review summary so the agent can answer directly
                if review_summary:
                    context_lines.append("")
                    context_lines.append("PREVIOUS REVIEW RESULTS (summary):")
                    context_lines.append(review_summary)

                context_lines.extend([
                    "",
                    "=== ROUTING INSTRUCTIONS ===",
                    "THIS IS A FOLLOW-UP QUESTION. Use TEMPLATE 4: FOLLOW_UP.",
                    "1. Route DIRECTLY to AccountingAgent. NEVER route to ProxyAgent.",
                    "2. AccountingAgent: Answer from the review data above if possible. Only call tools if the answer cannot be derived from the context.",
                    f"3. If you need fresh data, use run_id={prior_run_id} or client_id={prior_client_id}.",
                    "4. Do NOT start a new review. Do NOT ask the user for clarification unless genuinely ambiguous.",
                    "5. After AccountingAgent responds, go DIRECTLY to final answer. No other agents needed.",
                    "",
                    f"USER FOLLOW-UP QUESTION: {task_text}",
                ])
                task_text = "\n".join(context_lines)
                self.logger.info(
                    "Enriched follow-up task with prior run context run_id=%s client=%s user=%s has_summary=%s has_conv_ctx=%s",
                    prior_run_id,
                    prior_client_id,
                    user_id,
                    bool(review_summary),
                    bool(conv_ctx),
                )

        self.logger.debug("Task: %s", task_text)
        final_text = ""
        memory_store = await DatabaseFactory.get_database(user_id=user_id)

        try:
            start_ts = time.perf_counter()
            final_output: str | None = None
            self.logger.info(
                "Starting workflow execution user=%s session=%s run_id=%s",
                user_id,
                session_id,
                run_id,
            )
            _ORCHESTRATION_TIMEOUT_S = 600  # 10 minutes — generous safety margin for multi-step orchestration

            async def _consume_stream() -> None:
                nonlocal final_text, final_output
                async for event in workflow.run_stream(task_text):
                    await run_control_config.refresh_ttl(user_id=user_id, run_id=run_id)
                    try:
                        if isinstance(event, MagenticOrchestratorMessageEvent):
                            message_text = getattr(event.message, "text", "")
                            self.logger.info("[ORCHESTRATOR:%s] %s", event.kind, message_text)

                        elif isinstance(event, MagenticAgentDeltaEvent):
                            try:
                                await streaming_agent_response_callback(
                                    event.agent_id,
                                    event,
                                    False,
                                    user_id,
                                )
                            except Exception as e:
                                self.logger.error(
                                    "Error in streaming callback for agent %s: %s",
                                    event.agent_id,
                                    e,
                                )

                        elif isinstance(event, MagenticAgentMessageEvent):
                            if event.message:
                                try:
                                    await agent_response_callback(
                                        event.agent_id, event.message, user_id
                                    )
                                except Exception as e:
                                    self.logger.error(
                                        "Error in agent callback for agent %s: %s",
                                        event.agent_id,
                                        e,
                                    )
                                # Capture balance-sheet run_id from agent messages
                                msg_text = getattr(event.message, "text", "")
                                if msg_text:
                                    _try_capture_run_context(
                                        msg_text, user_id, session_id, task_text
                                    )

                        elif isinstance(event, MagenticFinalResultEvent):
                            final_text = getattr(event.message, "text", "")
                            self.logger.info("[FINAL RESULT] length=%d", len(final_text))

                        elif isinstance(event, WorkflowOutputEvent):
                            output_data = event.data
                            if isinstance(output_data, ChatMessage):
                                final_output = getattr(output_data, "text", None) or str(
                                    output_data
                                )
                            else:
                                final_output = str(output_data)

                    except Exception as e:
                        self.logger.error(
                            "Error processing event %s: %s",
                            type(event).__name__,
                            e,
                            exc_info=True,
                        )

            with traced_phase(
                "orchestration.workflow_stream",
                logger=self.logger,
                attributes={"run.id": run_id, "plan.id": plan_id, "user.id": user_id},
            ):
                try:
                    await asyncio.wait_for(_consume_stream(), timeout=_ORCHESTRATION_TIMEOUT_S)
                except asyncio.TimeoutError:
                    self.logger.error(
                        "Orchestration timed out after %ds user=%s run_id=%s",
                        _ORCHESTRATION_TIMEOUT_S,
                        user_id,
                        run_id,
                    )
                    final_text = (
                        "The review timed out. This usually means the backend pipeline "
                        "is taking longer than expected. Please try again."
                    )

            final_text = final_output if final_output else final_text
            self.logger.info(
                "Orchestration finished user=%s run_id=%s duration_s=%.2f final_len=%d",
                user_id,
                run_id,
                time.perf_counter() - start_ts,
                len(final_text),
            )

            # Capture run_id from final output for follow-up context
            if final_text:
                _try_capture_run_context(final_text, user_id, session_id, task_text)
                _capture_review_summary(final_text, user_id)

            # Sanitize before sending to UI — strip internal agent names, transfer
            # instructions, and citation markers so the user sees clean output.
            final_text = sanitize_for_display(clean_citations(final_text))

            await connection_config.send_status_update_async(
                {
                    "content": final_text,
                    "status": "completed",
                    "timestamp": asyncio.get_event_loop().time(),
                    "plan_id": plan_id,
                    "run_id": run_id,
                },
                user_id,
                message_type=WebsocketMessageType.FINAL_RESULT_MESSAGE,
            )

            plan = await memory_store.get_plan_by_plan_id(plan_id=plan_id)
            if plan:
                plan.overall_status = PlanStatus.completed
                plan.streaming_message = final_text
                await memory_store.update_plan(plan)

        except asyncio.CancelledError:
            cancel_message = "Run cancelled by user."
            self.logger.info(
                "Orchestration cancelled user=%s run_id=%s plan_id=%s",
                user_id,
                run_id,
                plan_id,
            )
            try:
                plan = await memory_store.get_plan_by_plan_id(plan_id=plan_id)
                if plan and plan.overall_status != PlanStatus.canceled:
                    plan.overall_status = PlanStatus.canceled
                    plan.streaming_message = cancel_message
                    await memory_store.update_plan(plan)
            except Exception as status_error:
                self.logger.warning(
                    "Unable to mark canceled status for plan_id=%s: %s",
                    plan_id,
                    status_error,
                )

            try:
                await connection_config.send_status_update_async(
                    {
                        "content": cancel_message,
                        "status": "canceled",
                        "timestamp": asyncio.get_event_loop().time(),
                        "plan_id": plan_id,
                        "run_id": run_id,
                    },
                    user_id,
                    message_type=WebsocketMessageType.FINAL_RESULT_MESSAGE,
                )
            except Exception as send_error:
                self.logger.warning(
                    "Unable to send canceled status for run_id=%s: %s",
                    run_id,
                    send_error,
                )
            raise
        except Exception as e:
            self.logger.error("Unexpected orchestration error: %s", e, exc_info=True)
            try:
                await connection_config.send_status_update_async(
                    {
                        "content": f"Error during orchestration: {str(e)}",
                        "status": "error",
                        "timestamp": asyncio.get_event_loop().time(),
                        "plan_id": plan_id,
                        "run_id": run_id,
                    },
                    user_id,
                    message_type=WebsocketMessageType.FINAL_RESULT_MESSAGE,
                )
            except Exception as send_error:
                self.logger.error("Failed to send error status: %s", send_error)

            try:
                plan = await memory_store.get_plan_by_plan_id(plan_id=plan_id)
                if plan:
                    plan.overall_status = PlanStatus.failed
                    plan.streaming_message = f"Error during orchestration: {str(e)}"
                    await memory_store.update_plan(plan)
            except Exception as status_error:
                self.logger.warning(
                    "Unable to mark failed status for plan_id=%s: %s",
                    plan_id,
                    status_error,
                )
            raise
        finally:
            await run_control_config.release_run(user_id=user_id, run_id=run_id)
            self.logger.info("Released run lock user=%s run_id=%s", user_id, run_id)

    # ---------------------------
    # Direct follow-up (fast path)
    # ---------------------------
    async def run_direct_followup(
        self,
        user_id: str,
        input_task,
        plan_id: str,
        run_id: str,
    ) -> None:
        """Execute a follow-up question by calling AccountingAgent directly.

        Bypasses the full Magentic orchestration loop (plan generation, routing,
        progress ledger, final-answer compilation) and invokes the cached
        AccountingAgent wrapper's ``invoke()`` method. This reduces a follow-up
        from ~4 LLM calls to exactly 1.

        Falls back to full orchestration if no cached agent is available.
        """
        self.logger.info(
            "Starting DIRECT follow-up run_id=%s plan_id=%s user=%s",
            run_id, plan_id, user_id,
        )

        # --- Find cached AccountingAgent wrapper ---
        wrappers = orchestration_config.agent_wrappers.get(user_id, [])
        accounting_agent = None
        for w in wrappers:
            name = getattr(w, "agent_name", None) or getattr(w, "name", "")
            if name.lower() == "accountingagent":
                accounting_agent = w
                break

        if accounting_agent is None:
            self.logger.warning(
                "No cached AccountingAgent for user=%s; falling back to full orchestration.",
                user_id,
            )
            return await self.run_orchestration(
                user_id=user_id,
                input_task=input_task,
                plan_id=plan_id,
                run_id=run_id,
            )

        # --- Build enriched prompt ---
        session_id = str(getattr(input_task, "session_id", "") or "")
        task_text = getattr(input_task, "description", str(input_task))

        # Load prior context (in-memory first, then Cosmos)
        prior_ctx = orchestration_config.workflow_last_run_context.get(user_id)
        if (not prior_ctx or prior_ctx.get("session_id") != session_id) and session_id:
            cosmos_ctx = get_session_context(user_id, session_id)
            if cosmos_ctx and cosmos_ctx.get("run_id"):
                prior_ctx = {
                    "run_id": cosmos_ctx["run_id"],
                    "session_id": cosmos_ctx.get("original_session_id", session_id),
                    "initial_goal": cosmos_ctx.get("initial_goal", ""),
                    "client_id": cosmos_ctx.get("client_id", ""),
                    "period_end": cosmos_ctx.get("period_end", ""),
                    "review_summary": cosmos_ctx.get("review_summary", ""),
                }
                orchestration_config.workflow_last_run_context[user_id] = prior_ctx
                self.logger.info(
                    "Re-hydrated context from Cosmos for direct follow-up user=%s run_id=%s",
                    user_id, prior_ctx["run_id"],
                )

        if prior_ctx and prior_ctx.get("session_id") == session_id:
            prior_run_id = prior_ctx["run_id"]
            context_lines = [
                "=== FOLLOW-UP CONTEXT (same session) ===",
                "",
                "PRIOR REVIEW DATA:",
                f"- Balance sheet review run_id: {prior_run_id}",
                f"- Original request: {prior_ctx.get('initial_goal', '')}",
            ]
            if prior_ctx.get("client_id"):
                context_lines.append(f"- Client ID (QBO realm): {prior_ctx['client_id']}")
            if prior_ctx.get("period_end"):
                context_lines.append(f"- Period end date: {prior_ctx['period_end']}")

            conv_ctx = getattr(input_task, "conversation_context", None) or []
            if conv_ctx:
                context_lines.append("")
                context_lines.append("RECENT CONVERSATION HISTORY:")
                for msg in conv_ctx[-8:]:
                    context_lines.append(f"  {msg}")

            review_summary = prior_ctx.get("review_summary", "")
            if review_summary:
                context_lines.append("")
                context_lines.append("PREVIOUS REVIEW RESULTS (summary):")
                context_lines.append(review_summary)

            context_lines.extend([
                "",
                "=== INSTRUCTIONS ===",
                "Answer this follow-up question using the context above.",
                "Only call tools if the answer cannot be derived from the provided context.",
                f"If you need fresh data, use run_id={prior_run_id}.",
                "",
                f"USER QUESTION: {task_text}",
            ])
            task_text = "\n".join(context_lines)

        self.logger.info(
            "Direct follow-up prompt built (%d chars) user=%s", len(task_text), user_id,
        )

        memory_store = await DatabaseFactory.get_database(user_id=user_id)
        final_text = ""

        try:
            start_ts = time.perf_counter()
            _DIRECT_TIMEOUT_S = 180  # 3 minutes — generous for single-agent call

            collected_chunks: list[str] = []

            async def _run_agent():
                nonlocal final_text
                async for update in accounting_agent.invoke(task_text):
                    await run_control_config.refresh_ttl(user_id=user_id, run_id=run_id)

                    # Extract text from streaming update
                    chunk_text = getattr(update, "text", None)
                    if not chunk_text:
                        contents = getattr(update, "contents", []) or []
                        parts = []
                        for item in contents:
                            txt = getattr(item, "text", None)
                            if txt:
                                parts.append(str(txt))
                        chunk_text = "".join(parts) if parts else ""

                    if chunk_text:
                        cleaned = sanitize_for_display(clean_citations(chunk_text))
                        if cleaned:
                            collected_chunks.append(cleaned)
                            # Stream directly to UI (bypass output gate)
                            await connection_config.send_status_update_async(
                                {
                                    "agent_name": "AccountingAgent",
                                    "content": cleaned,
                                    "is_final": False,
                                },
                                user_id,
                                message_type=WebsocketMessageType.AGENT_MESSAGE_STREAMING,
                            )

                    # Forward tool-call events for activity indicators
                    contents = getattr(update, "contents", []) or []
                    for item in contents:
                        if getattr(item, "content_type", None) == "function_call" or hasattr(item, "function_name"):
                            tool_name = getattr(item, "function_name", None) or getattr(item, "name", "tool_call")
                            await connection_config.send_status_update_async(
                                {
                                    "agent_name": "AccountingAgent",
                                    "tool_calls": [{"tool_name": str(tool_name)}],
                                },
                                user_id,
                                message_type=WebsocketMessageType.AGENT_TOOL_MESSAGE,
                            )

                final_text = "".join(collected_chunks)

            try:
                await asyncio.wait_for(_run_agent(), timeout=_DIRECT_TIMEOUT_S)
            except asyncio.TimeoutError:
                self.logger.error(
                    "Direct follow-up timed out after %ds user=%s run_id=%s",
                    _DIRECT_TIMEOUT_S, user_id, run_id,
                )
                final_text = "The follow-up timed out. Please try again."

            elapsed = time.perf_counter() - start_ts
            self.logger.info(
                "Direct follow-up completed user=%s run_id=%s duration_s=%.2f len=%d",
                user_id, run_id, elapsed, len(final_text),
            )

            # Capture context from output
            if final_text:
                _try_capture_run_context(final_text, user_id, session_id, task_text)
                _capture_review_summary(final_text, user_id)

            final_text = sanitize_for_display(clean_citations(final_text))

            # Send final result
            await connection_config.send_status_update_async(
                {
                    "content": final_text,
                    "status": "completed",
                    "timestamp": asyncio.get_event_loop().time(),
                    "plan_id": plan_id,
                    "run_id": run_id,
                },
                user_id,
                message_type=WebsocketMessageType.FINAL_RESULT_MESSAGE,
            )

            plan = await memory_store.get_plan_by_plan_id(plan_id=plan_id)
            if plan:
                plan.overall_status = PlanStatus.completed
                plan.streaming_message = final_text
                await memory_store.update_plan(plan)

        except asyncio.CancelledError:
            self.logger.info(
                "Direct follow-up cancelled user=%s run_id=%s", user_id, run_id,
            )
            try:
                plan = await memory_store.get_plan_by_plan_id(plan_id=plan_id)
                if plan and plan.overall_status != PlanStatus.canceled:
                    plan.overall_status = PlanStatus.canceled
                    plan.streaming_message = "Run cancelled by user."
                    await memory_store.update_plan(plan)
            except Exception:
                pass
            try:
                await connection_config.send_status_update_async(
                    {
                        "content": "Run cancelled by user.",
                        "status": "canceled",
                        "timestamp": asyncio.get_event_loop().time(),
                        "plan_id": plan_id,
                        "run_id": run_id,
                    },
                    user_id,
                    message_type=WebsocketMessageType.FINAL_RESULT_MESSAGE,
                )
            except Exception:
                pass
            raise
        except Exception as e:
            self.logger.error(
                "Direct follow-up error: %s", e, exc_info=True,
            )
            try:
                await connection_config.send_status_update_async(
                    {
                        "content": f"Error during follow-up: {str(e)}",
                        "status": "error",
                        "timestamp": asyncio.get_event_loop().time(),
                        "plan_id": plan_id,
                        "run_id": run_id,
                    },
                    user_id,
                    message_type=WebsocketMessageType.FINAL_RESULT_MESSAGE,
                )
            except Exception:
                pass
            try:
                plan = await memory_store.get_plan_by_plan_id(plan_id=plan_id)
                if plan:
                    plan.overall_status = PlanStatus.failed
                    plan.streaming_message = f"Error: {str(e)}"
                    await memory_store.update_plan(plan)
            except Exception:
                pass
            raise
        finally:
            await run_control_config.release_run(user_id=user_id, run_id=run_id)
            self.logger.info(
                "Released run lock (direct) user=%s run_id=%s", user_id, run_id,
            )
