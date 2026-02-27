"""
Magentic Manager with custom prompts for balance sheet review orchestration.
Extends StandardMagenticManager (agent_framework version).
"""

import asyncio
import logging
from typing import Any, Optional

import v4.models.messages as messages
from agent_framework import ChatMessage
from agent_framework._workflows._magentic import (
    MagenticContext,
    StandardMagenticManager,
    ORCHESTRATOR_FINAL_ANSWER_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT,
)

from v4.config.settings import connection_config, orchestration_config
from v4.models.models import MPlan
from v4.orchestration.helper.plan_to_mplan_converter import PlanToMPlanConverter

logger = logging.getLogger(__name__)


class HumanApprovalMagenticManager(StandardMagenticManager):
    """
    Magentic manager with custom orchestration prompts for balance sheet review workflows.
    Approval gate is disabled — the orchestrator routes directly to agents without user friction.
    """

    approval_enabled: bool = True
    magentic_plan: Optional[MPlan] = None
    current_user_id: str  # populated in __init__

    def __init__(self, user_id: str, *args, **kwargs):
        """
        Initialize the HumanApprovalMagenticManager.
        Args:
            user_id: ID of the user to associate with this orchestration instance.
            *args: Additional positional arguments for the parent StandardMagenticManager.
            **kwargs: Additional keyword arguments for the parent StandardMagenticManager.
        """

        plan_append = """

IMPORTANT: Never ask the user for information or clarification until all agents on the team have been asked first.

EXAMPLE: If the user request involves product information, first ask all agents on the team to provide the information.
Do not ask the user unless all agents have been consulted and the information is still missing.

Plan steps should always include a bullet point, followed by an agent name, followed by a description of the action
to be taken. If a step involves multiple actions, separate them into distinct steps with an agent included in each step.
If the step is taken by an agent that is not part of the team, such as the MagenticManager, please always list the MagenticManager as the agent for that step. At any time, if more information is needed from the user, use the ProxyAgent to request this information.
The first plan step must always be a MagenticManager orchestration step that states it will coordinate the team.
Every plan step — including steps 2, 3, and all subsequent steps — MUST start with the assigned agent name in bold (e.g. **ReviewAgent**, **ProxyAgent**). Never omit the agent name from any step.

BALANCE SHEET REVIEW — PIPELINE FLOW (when a full review is requested):
  **ReviewAgent** → calls qbo_connection_status, then run_balance_sheet_review (single synchronous call that runs the full pipeline), returns structured JSON with run_id, findings, balance_sheet_rows, hitl_requests

FLEXIBLE FLOW — NOT every query requires a full review run. Route based on user intent:
  - "Is QBO connected?" or "check QBO status" → **ReviewAgent** (qbo_connection_status) → **ProxyAgent**
  - "Run balance sheet review for client X" → **ReviewAgent** (run_balance_sheet_review) → **ProxyAgent**
  - "What were the findings from run <run_id>?" → **ReviewAgent** (get_balance_sheet_review) → **ProxyAgent**
  - "Why did cash fail?" or follow-up questions → **ReviewAgent** (get_balance_sheet_review with prior run_id) → **ProxyAgent**

If ReviewAgent reports QBO disconnected or unauthorized, terminate the workflow immediately after providing the connect URL through ProxyAgent, and do not attempt the review.
If ReviewAgent reports a transient tool or network failure, retry the same step up to 2 times before escalating to ProxyAgent.
For follow-up questions about a previous review, ReviewAgent uses the same run_id from context and calls get_balance_sheet_review — do NOT trigger a new run unless the user explicitly requests a fresh review.
"""

        final_append = """
DO NOT EVER OFFER TO HELP FURTHER IN THE FINAL ANSWER! Just provide the final answer and end with a polite closing.

BALANCE SHEET REVIEW OUTPUT FORMAT — When the task involves a balance sheet review and the conversation contains balance_sheet_rows data, structure your final answer as follows:

1. **Executive Summary** — 3-5 sentences on the client's overall financial position and most critical concerns.

2. **## Balance Sheet** — Render ALL rows from balance_sheet_rows as a markdown table. Add a `### [Section]` heading before each distinct account section group (e.g. ### Assets, ### Current Liabilities, ### Non-current Liabilities, ### Equity). Columns: | Account | Balance | Status | Notes |. Status emoji: ✅ PASS · ❌ FAIL · ⚠️ NEEDS REVIEW · — (NOT_APPLICABLE). Show the row's `flag` in Notes if non-empty, otherwise leave blank. Format balance values with two decimal places.

3. **## Issues Requiring Attention** — Bullet list of every ❌ FAIL and ⚠️ NEEDS REVIEW account, showing the account name, flag description, and required action from balance_sheet_rows.

4. **## Recommended Next Steps** — Numbered list of 3-6 concrete actions ordered by urgency.
"""

        kwargs["task_ledger_plan_prompt"] = (
            ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT + plan_append
        )
        kwargs["task_ledger_plan_update_prompt"] = (
            ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT + plan_append
        )
        kwargs["final_answer_prompt"] = ORCHESTRATOR_FINAL_ANSWER_PROMPT + final_append

        self.current_user_id = user_id
        super().__init__(*args, **kwargs)

    async def plan(self, magentic_context: MagenticContext) -> Any:
        """
        Generate the orchestration plan and proceed immediately — no user approval gate.

        Plan approval adds friction for deterministic, predictable workflows such as
        balance sheet reviews. The orchestrator routes directly to agents without waiting
        for the user to click "Approve", which eliminates the stuck-waiting failure mode
        and the "failed to submit approval" error that occurs when the backend has already
        moved past the approval state by the time the user clicks.
        """
        task_text = getattr(magentic_context.task, "text", str(magentic_context.task))
        logger.info("Creating plan (approval gate disabled): task=%.120s", task_text)
        return await super().plan(magentic_context)

    async def replan(self, magentic_context: MagenticContext) -> Any:
        """
        Override to add websocket messages for replanning events.
        """
        logger.info("\nHuman-in-the-Loop Magentic Manager replanned:")
        replan_message = await super().replan(magentic_context=magentic_context)
        logger.info(
            "Replanned message length: %d",
            len(replan_message.text) if replan_message and replan_message.text else 0,
        )
        return replan_message

    async def create_progress_ledger(self, magentic_context: MagenticContext):
        """
        Check for max rounds exceeded and send final message if so, else defer to base.

        Returns:
            Progress ledger object (type depends on agent_framework version)
        """
        if magentic_context.round_count >= orchestration_config.max_rounds:
            final_message = messages.FinalResultMessage(
                content="Process terminated: Maximum rounds exceeded",
                status="terminated",
                summary=f"Stopped after {magentic_context.round_count} rounds (max: {orchestration_config.max_rounds})",
            )

            await connection_config.send_status_update_async(
                message=final_message,
                user_id=self.current_user_id,
                message_type=messages.WebsocketMessageType.FINAL_RESULT_MESSAGE,
            )

            # Call base class to get the proper ledger type, then raise to terminate
            ledger = await super().create_progress_ledger(magentic_context)

            # Override key fields to signal termination
            ledger.is_request_satisfied.answer = True
            ledger.is_request_satisfied.reason = "Maximum rounds exceeded"
            ledger.is_in_loop.answer = False
            ledger.is_in_loop.reason = "Terminating"
            ledger.is_progress_being_made.answer = False
            ledger.is_progress_being_made.reason = "Terminating"
            ledger.next_speaker.answer = ""
            ledger.next_speaker.reason = "Task complete"
            ledger.instruction_or_question.answer = "Process terminated due to maximum rounds exceeded"
            ledger.instruction_or_question.reason = "Task complete"

            return ledger

        # Delegate to base for normal progress ledger creation
        return await super().create_progress_ledger(magentic_context)

    async def _wait_for_user_approval(
        self, m_plan_id: Optional[str] = None
    ) -> Optional[messages.PlanApprovalResponse]:
        """
        Wait for user approval response using event-driven pattern with timeout handling.
        """
        logger.info("Waiting for user approval for plan: %s", m_plan_id)

        if not m_plan_id:
            logger.error("No plan ID provided for approval")
            return messages.PlanApprovalResponse(approved=False, m_plan_id=m_plan_id)

        orchestration_config.set_approval_pending(m_plan_id)

        try:
            approved = await orchestration_config.wait_for_approval(m_plan_id)
            logger.info("Approval received for plan %s: %s", m_plan_id, approved)
            return messages.PlanApprovalResponse(approved=approved, m_plan_id=m_plan_id)

        except asyncio.TimeoutError:
            logger.debug(
                "Approval timeout for plan %s - notifying user and terminating process",
                m_plan_id,
            )

            timeout_message = messages.TimeoutNotification(
                timeout_type="approval",
                request_id=m_plan_id,
                message=f"Plan approval request timed out after {orchestration_config.default_timeout} seconds. Please try again.",
                timestamp=asyncio.get_event_loop().time(),
                timeout_duration=orchestration_config.default_timeout,
            )

            try:
                await connection_config.send_status_update_async(
                    message=timeout_message,
                    user_id=self.current_user_id,
                    message_type=messages.WebsocketMessageType.TIMEOUT_NOTIFICATION,
                )
                logger.info(
                    "Timeout notification sent to user %s for plan %s",
                    self.current_user_id,
                    m_plan_id,
                )
            except Exception as e:
                logger.error("Failed to send timeout notification: %s", e)

            orchestration_config.cleanup_approval(m_plan_id)
            return None

        except KeyError as e:
            logger.debug("Plan ID not found: %s - terminating process silently", e)
            return None

        except asyncio.CancelledError:
            logger.debug("Approval request %s was cancelled", m_plan_id)
            orchestration_config.cleanup_approval(m_plan_id)
            return None

        except Exception as e:
            logger.debug(
                "Unexpected error waiting for approval: %s - terminating process silently",
                e,
            )
            orchestration_config.cleanup_approval(m_plan_id)
            return None

        finally:
            if (
                m_plan_id in orchestration_config.approvals
                and orchestration_config.approvals[m_plan_id] is None
            ):
                logger.debug("Final cleanup for pending approval plan %s", m_plan_id)
                orchestration_config.cleanup_approval(m_plan_id)

    async def prepare_final_answer(
        self, magentic_context: MagenticContext
    ) -> ChatMessage:
        """
        Override to ensure final answer is prepared after all steps are executed.
        """
        logger.info("\n Magentic Manager - Preparing final answer...")
        return await super().prepare_final_answer(magentic_context)

    def plan_to_obj(self, magentic_context: MagenticContext, ledger) -> MPlan:
        """Convert the generated plan from the ledger into a structured MPlan object."""
        if (
            ledger is None
            or not hasattr(ledger, "plan")
            or not hasattr(ledger, "facts")
        ):
            raise ValueError(
                "Invalid ledger structure; expected plan and facts attributes."
            )

        task_text = getattr(magentic_context.task, "text", str(magentic_context.task))

        return_plan: MPlan = PlanToMPlanConverter.convert(
            plan_text=getattr(ledger.plan, "text", ""),
            facts=getattr(ledger.facts, "text", ""),
            team=list(magentic_context.participant_descriptions.keys()),
            task=task_text,
        )

        return return_plan
