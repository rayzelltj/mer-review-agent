"""
Shared review-context object threaded through the multi-agent balance-sheet workflow.

Every agent that participates in a balance-sheet review MUST receive the same
ReviewContext so there is exactly one authoritative run_id in flight.

Usage (orchestration_manager.py, in run_orchestration):
    review_ctx = ReviewContext.from_task(task_text, user_id)
    orchestration_config.set_review_context(user_id, review_ctx)
    # Prepend a compact JSON header to the task so every agent sees it:
    task_with_ctx = review_ctx.inject_into_task(task_text)

In agent system messages reference the values with:
    "Use the run_id from the REVIEW_CONTEXT block at the top of your task; never
     call start_balance_sheet_review more than once per workflow invocation."
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Canonical statuses
# ---------------------------------------------------------------------------
RunStatus = Literal["queued", "running", "done", "failed"]
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "failed"})


# ---------------------------------------------------------------------------
# Internal evidence / rules schemas
# (These travel as JSON inside agent messages – never rendered to the user.)
# ---------------------------------------------------------------------------

@dataclass
class EvidenceItem:
    """A single piece of evidence gathered for a rules check."""
    rule_id: str
    evidence_type: str          # e.g. "qbo_balance", "drive_document"
    source: str                 # e.g. "QBO", "Drive"
    value: Optional[Any] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    """Aggregated evidence for a full balance-sheet review run."""
    run_id: str
    client_id: str
    period_end: str             # ISO-8601 date string "YYYY-MM-DD"
    items: List[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "client_id": self.client_id,
            "period_end": self.period_end,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class RuleResultSummary:
    """Compact rule result for intra-agent JSON payloads."""
    rule_id: str
    title: str
    status: Literal["PASS", "FAIL", "NEEDS_REVIEW", "SKIPPED"]
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewSummary:
    """Internal summary passed from RulesAgent → ReportAgent (JSON only, never HTML)."""
    run_id: str
    client_id: str
    period_end: str
    run_status: RunStatus
    total_rules: int = 0
    pass_count: int = 0
    fail_count: int = 0
    needs_review_count: int = 0
    skipped_count: int = 0
    rule_results: List[RuleResultSummary] = field(default_factory=list)
    hitl_requests: List[Dict[str, Any]] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "client_id": self.client_id,
            "period_end": self.period_end,
            "run_status": self.run_status,
            "total_rules": self.total_rules,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "needs_review_count": self.needs_review_count,
            "skipped_count": self.skipped_count,
            "rule_results": [r.to_dict() for r in self.rule_results],
            "hitl_requests": self.hitl_requests,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ReviewContext – the single authoritative context object for one workflow run
# ---------------------------------------------------------------------------

@dataclass
class ReviewContext:
    """
    Shared context object for a single balance-sheet review workflow execution.

    One ReviewContext is created at orchestration start and threaded through
    every agent invocation as an immutable header block.

    Fields
    ------
    correlation_id : Unique ID for *this* orchestration run (UUID hex).
                     Used to detect retries: if the orchestrator replans and
                     ConnectorAgent fires again, the same correlation_id lets
                     `get_or_create_balance_sheet_review` return the already-
                     created run rather than spawning a new one.
    run_id         : The balance-sheet review run_id produced by ConnectorAgent.
                     Set to None until ConnectorAgent has created/found the run.
    user_id        : The authenticated user_principal_id.
    client_id      : The QBO client being reviewed.
    period_end     : ISO-8601 date string "YYYY-MM-DD".
    run_status     : Most-recently known run status.
    created_at     : UTC ISO-8601 timestamp when this context was created.
    """
    correlation_id: str
    user_id: str
    client_id: Optional[str] = None
    period_end: Optional[str] = None
    run_id: Optional[str] = None
    run_status: Optional[RunStatus] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def new(cls, user_id: str, client_id: Optional[str] = None, period_end: Optional[str] = None) -> "ReviewContext":
        """Create a fresh ReviewContext with a new correlation_id."""
        return cls(
            correlation_id=uuid.uuid4().hex,
            user_id=user_id,
            client_id=client_id,
            period_end=period_end,
        )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_task_header(self) -> str:
        """
        Return a compact JSON block suitable for prepending to an agent task.

        Agents are instructed via their system_message to:
          1. Parse this block.
          2. Use run_id (if set) rather than calling start_balance_sheet_review.
          3. Use get_or_create_balance_sheet_review(client_id, period_end, correlation_id).
        """
        import json
        payload = {
            "correlation_id": self.correlation_id,
            "user_id": self.user_id,
        }
        if self.client_id:
            payload["client_id"] = self.client_id
        if self.period_end:
            payload["period_end"] = self.period_end
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.run_status:
            payload["run_status"] = self.run_status
        return f"REVIEW_CONTEXT:{json.dumps(payload, separators=(',', ':'))}"

    def inject_into_task(self, task_text: str) -> str:
        """Prepend the review context header to a task string."""
        return f"{self.to_task_header()}\n\n{task_text}"

    # ------------------------------------------------------------------
    # Mutation helpers (used by orchestration_manager after ConnectorAgent)
    # ------------------------------------------------------------------

    def set_run_id(self, run_id: str, status: Optional[RunStatus] = None) -> "ReviewContext":
        """Return a new ReviewContext with run_id (and optionally status) set."""
        return ReviewContext(
            correlation_id=self.correlation_id,
            user_id=self.user_id,
            client_id=self.client_id,
            period_end=self.period_end,
            run_id=run_id,
            run_status=status or self.run_status,
            created_at=self.created_at,
        )

    @property
    def is_terminal(self) -> bool:
        return self.run_status in TERMINAL_STATUSES
