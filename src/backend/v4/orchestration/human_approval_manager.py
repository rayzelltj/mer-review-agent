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

Plan steps should always include a bullet point, followed by an agent name, followed by a description of the action to be taken. If a step involves multiple actions, separate them into distinct steps with an agent included in each step. The first plan step must always be a MagenticManager orchestration step that states it will coordinate the team. Every plan step MUST start with the assigned agent name in bold.

## WORKFLOW TEMPLATES — Select based on user intent:

### TEMPLATE 1: FULL_REVIEW
Triggered by: "Run balance sheet review", "Review client X for period Y"
1. **MagenticManager** — Coordinate balance sheet review workflow
2. **AccountingAgent** — Check QBO connection, run or retrieve review, investigate findings, log evidence, present results
3. **MagenticManager** — Compile final report from AccountingAgent results

### TEMPLATE 2: INVESTIGATE
Triggered by: "Why did X fail?", "Investigate variance in Y", "What caused Z?", "Dig deeper into X"
1. **MagenticManager** — Coordinate investigation workflow
2. **AccountingAgent** — Load prior run, form hypotheses, gather evidence, reach conclusion, present findings
3. **MagenticManager** — Present investigation findings

### TEMPLATE 3: DATA_QUERY
Triggered by: "Show me AR aging", "What's the trial balance?", "List accounts", any QBO data request
1. **MagenticManager** — Coordinate data query
2. **AccountingAgent** — Call appropriate QBO data tool, format and present response
3. **MagenticManager** — Present data as formatted by AccountingAgent

### TEMPLATE 4: FOLLOW_UP
Triggered by: ANY follow-up question in same session about a prior review. This includes: "Why did X fail?", "Tell me more about X", "What bank accounts are there?", "Dig deeper into X", any question after a review has completed.
1. **MagenticManager** — Coordinate follow-up (route to AccountingAgent ONLY)
2. **AccountingAgent** — Answer from review context or call tools if needed
3. **MagenticManager** — Present answer

### TEMPLATE 5: CORRECTION
Triggered by: "That's wrong", "Actually it should be", "Ignore X in future"
1. **MagenticManager** — Coordinate correction storage
2. **AccountingAgent** — Parse correction, validate, store via store_correction tool
3. **MagenticManager** — Confirm correction saved

### TEMPLATE 6: EXPLAIN
Triggered by: "Explain X", "What does this rule check?", "Why is this important?"
1. **MagenticManager** — Coordinate explanation
2. **AccountingAgent** — Retrieve relevant context, explain in accounting terms
3. **MagenticManager** — Present explanation

## CRITICAL ROUTING RULES

### AccountingAgent — THE ONLY WORKER AGENT
- AccountingAgent handles ALL financial tasks: reviews, data queries, investigations, follow-ups, explanations, corrections.
- AccountingAgent speaks directly to the user in clear professional English.
- AccountingAgent is called AT MOST TWICE per workflow.
- After AccountingAgent responds, proceed DIRECTLY to MagenticManager final answer. No more agents needed.
- There is NO ProxyAgent. If AccountingAgent needs to ask the user a question, it asks directly in its response.

### Follow-up Detection
If the task text contains "FOLLOW-UP CONTEXT" or "PREVIOUS RUN IN THIS SESSION" or references a prior run_id, this IS a follow-up — use TEMPLATE 4 and route to AccountingAgent.

### Standard Flow
The standard workflow is always: MagenticManager → AccountingAgent → MagenticManager (final answer). That's it. Maximum 3 steps.
"""

        final_append = """
DO NOT EVER OFFER TO HELP FURTHER IN THE FINAL ANSWER! Just provide the final answer and end with a polite closing.

IMPORTANT OUTPUT RULES:
- NEVER include internal agent names (AccountingAgent, ProxyAgent, MagenticManager, ReviewAgent) in the final answer
- NEVER include phrases like "Transferred to...", "adopt the persona", or any routing/handoff language — these are internal
- NEVER start with "Transferred to" — if your draft starts with those words, delete it and write a clean response
- NEVER return raw JSON — always format data as readable markdown
- NEVER mention tool names (e.g. get_or_create_balance_sheet_review, bs_run_rules) — describe what happened in plain English
- Present AccountingAgent's analysis directly as your own response — speak as "I" or use passive voice
- If AccountingAgent returned a clear, well-formatted answer, use it as-is (just clean up any internal references)

## OUTPUT FORMAT BY RESPONSE TYPE:

### FOR DATA QUERIES (AR aging, trial balance, account listings, etc.)
Present the data AccountingAgent retrieved in a clean markdown table with a brief interpretation.
Example:
"## AR Aging — [Client Name] as of [Date]
| Bucket | Amount |
|--------|--------|
| Current | $0.00 |
| ... | ... |

[Brief interpretation of the data]"

### FOR INVESTIGATIONS
Present the finding, evidence gathered, and conclusion clearly. Reference specific accounts and amounts.

### FOR FOLLOW-UPS
Answer the question directly using the data from the prior review.

### FOR CORRECTIONS
Confirm what was stored and how it will affect future reviews.

### FOR EXPLANATIONS
Present the explanation in clear accounting terms.

### FOR BALANCE SHEET REVIEWS
When the task involves a balance sheet review and the conversation contains balance_sheet_rows data, structure your final answer as follows:

1. **Executive Summary** — 3-5 sentences on the client's overall financial position and most critical concerns.

2. **## Balance Sheet as of [period_end]** — Render EVERY row from balance_sheet_rows as a markdown table, preserving the QBO account hierarchy. Group rows by their `section` field and add a section heading (e.g. `### Bank`, `### Accounts Receivable`, `### Other Current Asset`, `### Fixed Asset`, `### Other Asset`, `### Accounts Payable`, `### Credit Card`, `### Other Current Liability`, `### Long Term Liability`, `### Equity`). Use the exact section names from the data. Within each section, list accounts in the order they appear. Include total/summary rows (where is_total=true) at the bottom of their section.

   Table columns: | Account | Balance | Status | Details |
   - **Account**: The account name. Indent sub-accounts if the hierarchy is apparent.
   - **Balance**: Formatted with commas and two decimal places (e.g. 254,403.55). Negative values in parentheses.
   - **Status**: ✅ PASS · ❌ FAIL · ⚠️ NEEDS REVIEW · — (for NOT_APPLICABLE, meaning no rule applies to this account)
   - **Details**: The row's `flag` text if non-empty. For NOT_APPLICABLE rows, leave blank.

   IMPORTANT: Include ALL accounts — not just those with findings. Accounts with status NOT_APPLICABLE and no flag should still appear with "—" status and blank Details. This gives a complete picture of the balance sheet.

3. **## Rules Not Tied to Specific Accounts** — If there are any unmapped findings or rules that apply globally (not to a specific account), list them here with their status and explanation.

4. **## Issues Requiring Attention** — Bullet list of every ❌ FAIL and ⚠️ NEEDS REVIEW item. For each, state: the account name, what the issue is (from the flag), and the specific action required (from the action field). Be specific — reference actual account names, dollar amounts, and dates.

5. **## Recommended Next Steps** — Numbered list of 3-6 concrete actions ordered by urgency. Reference specific accounts and amounts where applicable.
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
