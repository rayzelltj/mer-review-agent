"""Evidence Ledger — structured audit trail for agent reasoning."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class StepType(str, Enum):
    HYPOTHESIS = "hypothesis"
    TOOL_CALL = "tool_call"
    EVIDENCE = "evidence"
    CONCLUSION = "conclusion"
    ESCALATION = "escalation"
    CORRECTION_APPLIED = "correction_applied"


@dataclass
class EvidenceLedgerEntry:
    """A single reasoning step recorded in the evidence ledger."""

    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    agent: str = ""
    step_type: str = StepType.EVIDENCE.value
    content: str = ""
    tool_name: Optional[str] = None
    tool_input_summary: Optional[str] = None  # PII-scrubbed
    tool_output_summary: Optional[str] = None  # max 500 chars
    confidence: Optional[float] = None  # 0.0-1.0
    parent_entry_id: Optional[str] = None  # links to hypothesis

    def to_dict(self) -> dict:
        """Serialize to dict, omitting None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class EvidenceLedger:
    """Collection of reasoning steps for a balance sheet review run."""

    ledger_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    client_id: str = ""
    period_end: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    entries: list[EvidenceLedgerEntry] = field(default_factory=list)

    def add_entry(self, entry: EvidenceLedgerEntry) -> None:
        """Add an entry and link it to this ledger's run_id."""
        entry.run_id = self.run_id
        self.entries.append(entry)

    def get_hypothesis_chain(self, hypothesis_id: str) -> list[EvidenceLedgerEntry]:
        """Get a hypothesis and all evidence entries that tested it."""
        return [
            e
            for e in self.entries
            if e.entry_id == hypothesis_id or e.parent_entry_id == hypothesis_id
        ]

    def to_audit_trail(self) -> str:
        """Render as human-readable audit trail document."""
        lines = [f"# Evidence Ledger — Run {self.run_id}", ""]
        for e in self.entries:
            prefix = {
                "hypothesis": "H",
                "tool_call": "T",
                "evidence": "E",
                "conclusion": "C",
                "escalation": "!",
                "correction_applied": "P",
            }.get(e.step_type, "-")
            conf = f" (confidence: {e.confidence:.0%})" if e.confidence else ""
            lines.append(f"[{prefix}] [{e.timestamp[:19]}] {e.content}{conf}")
            if e.tool_name:
                lines.append(f"   Tool: {e.tool_name}")
            if e.tool_output_summary:
                lines.append(f"   Result: {e.tool_output_summary[:200]}")
            lines.append("")

        return "\n".join(lines)

    def to_cosmos_doc(self, session_id: str) -> dict:
        """Serialize to a Cosmos DB document."""
        return {
            "id": self.ledger_id,
            "session_id": session_id,
            "data_type": "evidence_ledger",
            "run_id": self.run_id,
            "client_id": self.client_id,
            "period_end": self.period_end,
            "created_at": self.created_at,
            "entry_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }
