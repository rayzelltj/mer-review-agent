# MER Agent V2 — Implementation Specification

> **Status:** APPROVED — ready for implementation  
> **Date:** 2026-03-02  
> **Applies ADRs:** 001-010  
> **Dependencies:** No new infrastructure required for Phases 0-2

---

## Table of Contents

1. [Current State Summary](#1-current-state-summary)
2. [Target Architecture](#2-target-architecture)
3. [Phase 0: Quick Win (1 day)](#3-phase-0-quick-win)
4. [Phase 1: AccountingAgent + Evidence Ledger (2-3 weeks)](#4-phase-1-accountingagent--evidence-ledger)
5. [Phase 2: Correction Memory (2 weeks)](#5-phase-2-correction-memory)
6. [Phase 3: Data Query Mode + PrepAgent (3-4 weeks)](#6-phase-3-data-query-mode--prepagent)
7. [Phase 4: RAG Knowledge Base (2-3 weeks)](#7-phase-4-rag-knowledge-base)
8. [Agent System Prompts (Final)](#8-agent-system-prompts)
9. [New MCP Tools Specification](#9-new-mcp-tools-specification)
10. [Cost & Latency Projections](#10-cost--latency-projections)
11. [Risk Register](#11-risk-register)
12. [Success Metrics](#12-success-metrics)
13. [Testing Strategy](#13-testing-strategy)

---

## 1. Current State Summary

### What exists and works

| Component | Status | Details |
|---|---|---|
| **ReviewAgent** | Deployed, functional | Calls `get_or_create_balance_sheet_review` → returns JSON |
| **ProxyAgent** | Deployed, functional | Human clarification relay |
| **35 MCP tools** | Registered, 32 unused | 16 QBO query tools, 4 Drive tools, 5 pipeline tools, 5 review tools, 5 snapshot/artifact tools |
| **23 rules** | Implemented, tested | BS-prefixed balance sheet rules with evidence requirements |
| **Rules engine** | Production-ready | Parallel execution, decorator registry, `RuleContext`, `ClientRulesConfig` |
| **QBO connector** | Production, retry+auth | `qbo_get()` with 401-refresh, 429/5xx retry, OpenTelemetry |
| **Drive connector** | Functional | OAuth2, file listing, content retrieval |
| **Cosmos DB** | Single container | `balance_sheet_run`, `qbo_client`, plans, steps, agents |
| **Blob Storage** | Snapshots + artifacts | `BlobSnapshotStore`, `BlobRunArtifactStore` |
| **WebSocket** | Streaming | Message types: AGENT_MESSAGE, STREAMING, TOOL, FINAL_RESULT |
| **Orchestrator** | Magentic workflow | 20 rounds max, 3 stall count, 600s timeout, per-user run lock |

### What doesn't exist

| Component | Impact |
|---|---|
| Correction/feedback memory | Agent cannot learn from user corrections |
| Evidence ledger | No audit trail of reasoning steps |
| Investigation workflow | Agent cannot drill into variances |
| Context budgeting | Token explosion risk on data-heavy queries |
| MER narrative generation | Cannot produce human-readable MER commentary |
| Escalation model | Agent doesn't know when to stop |
| Ad-hoc data query mode | Agent only runs full reviews, can't answer targeted questions |

### Architecture constraints (MUST preserve)

1. Rules engine is deterministic — LLM interprets, never evaluates
2. All secrets/auth server-side — frontend is display-only
3. Single Cosmos container with `data_type` discrimination
4. MCP server as separate Container App (port 9000)
5. Magentic orchestrator with `HumanApprovalMagenticManager`
6. Agent creation via `MagenticAgentFactory.create_agent_from_config()`
7. WebSocket streaming via `response_handlers.py`

---

## 2. Target Architecture

### Agent Evolution Map

```
v1 (Current)                    v2 (Target)
─────────────                   ────────────
Orchestrator ─── ReviewAgent    Orchestrator ─── AccountingAgent
             └── ProxyAgent                  ├── ProxyAgent
                                             └── (Phase 3) PrepAgent
```

### System Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend (React)                                                │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────────┐ │
│  │ HomeInput │  │  PlanPage    │  │  Balance Sheet Review Panel │ │
│  │          │  │  (chat+WS)   │  │  (structured output)       │ │
│  └──────────┘  └──────┬───────┘  └────────────────────────────┘ │
│                       │ WebSocket                                │
└───────────────────────┼──────────────────────────────────────────┘
                        │
┌───────────────────────┼──────────────────────────────────────────┐
│  Backend (FastAPI)    │                                          │
│  ┌────────────────────▼──────────────────────────────────────┐  │
│  │  HumanApprovalMagenticManager                             │  │
│  │  ┌─────────────────────────┐                              │  │
│  │  │ Workflow Template Router │◄── 6 templates (ADR-002)    │  │
│  │  └────────┬────────────────┘                              │  │
│  │           │ routes to                                     │  │
│  │  ┌────────▼────────┐  ┌──────────┐  ┌──────────────────┐ │  │
│  │  │ AccountingAgent │  │ProxyAgent│  │ PrepAgent (Ph.3) │ │  │
│  │  │ (review+invest) │  │ (human)  │  │ (narratives)     │ │  │
│  │  └────────┬────────┘  └──────────┘  └──────────────────┘ │  │
│  │           │ calls                                         │  │
│  └───────────┼───────────────────────────────────────────────┘  │
│              │ MCP                                               │
│  ┌───────────▼───────────────────────────────────────────────┐  │
│  │  35 MCP Tools (finance_service.py)                        │  │
│  │  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌───────────────┐  │  │
│  │  │ Review   │ │ QBO Data │ │ Drive  │ │ Snapshots     │  │  │
│  │  │ Pipeline │ │ (16)     │ │ (4)    │ │ & Artifacts   │  │  │
│  │  └──────────┘ └──────────┘ └────────┘ └───────────────┘  │  │
│  │  + NEW (Phase 2-3):                                       │  │
│  │  ┌──────────────┐ ┌─────────────────┐ ┌───────────────┐  │  │
│  │  │ Corrections  │ │ Evidence Ledger │ │ MER Narrative │  │  │
│  │  │ (5 tools)    │ │ (3 tools)       │ │ (2 tools)     │  │  │
│  │  └──────────────┘ └─────────────────┘ └───────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Data Layer                                                │  │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐ │  │
│  │  │ Cosmos DB│ │ Blob     │ │ QBO API    │ │ Google     │ │  │
│  │  │ (state)  │ │ (files)  │ │ (source)   │ │ Drive      │ │  │
│  │  └──────────┘ └──────────┘ └────────────┘ └────────────┘ │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Why 3 agents, not 6

Per ADR-001, we merge Analyst + Investigator into AccountingAgent. The Memory/Data agents from the prior proposal are unnecessary as separate agents because:

1. **MemoryAgent** → correction retrieval is a tool call, not an agent role. AccountingAgent calls `retrieve_corrections(client_id, rule_id)` — no separate agent needed.
2. **DataAgent** → AccountingAgent already has access to all 35 tools. A dedicated "data retriever" agent adds a coordination hop with zero benefit.
3. **InvestigatorAgent** → investigation is a operating mode of AccountingAgent, not a separate entity. The agent reasons about what to investigate, calls tools to gather evidence, and reaches conclusions — all within one context window.

**PrepAgent** remains separate (Phase 3) because narrative generation is a distinct capability that benefits from different temperature settings and a specialized prompt focused on writing quality rather than analytical accuracy.

---

## 3. Phase 0: Quick Win

**Goal:** Unlock 32 unused tools with zero new code. Validate the hypothesis that existing tools + better prompts = capable analyst.

**Timeline:** 1 day  
**Risk:** Low (fully reversible)  
**New code:** 0 lines  
**Changes:** 2 config/prompt files

### Change 1: `tool_choice` → `"auto"`

**File:** [src/backend/v4/magentic_agents/foundry_agent.py](src/backend/v4/magentic_agents/foundry_agent.py)

```python
# BEFORE
def _mcp_tool_choice(self, tools: List) -> str:
    if not tools:
        return "none"
    force_required = os.getenv("MCP_TOOL_CHOICE_REQUIRED", "").strip().lower()
    if force_required in {"0", "false", "no", "off"}:
        return "auto"
    return "required"   # ← DEFAULT

# AFTER
def _mcp_tool_choice(self, tools: List) -> str:
    if not tools:
        return "none"
    force_required = os.getenv("MCP_TOOL_CHOICE_REQUIRED", "").strip().lower()
    if force_required in {"1", "true", "yes", "on"}:
        return "required"
    return "auto"   # ← NEW DEFAULT
```

**OR** (simpler): Set env var `MCP_TOOL_CHOICE_REQUIRED=false` in Container App settings.

### Change 2: Expanded ReviewAgent System Prompt

**File:** [data/agent_teams/balance_sheet_review_team.json](data/agent_teams/balance_sheet_review_team.json)

Replace the `system_message` for ReviewAgent. The new prompt is in [Section 8](#8-agent-system-prompts).

### Change 3: Expanded Plan Prompt Templates

**File:** [src/backend/v4/orchestration/human_approval_manager.py](src/backend/v4/orchestration/human_approval_manager.py)

Expand `plan_append` to include the 6 workflow templates. See [Section 8.4](#84-orchestrator-plan-prompt-expansion).

### Validation

1. Run existing tests: `cd src/backend && uv run pytest --tb=short -q`
2. Manual test: "Run balance sheet review for client X, period 2026-01-31"
3. Manual test: "Why did the bank reconciliation rule fail?"
4. Manual test: "Show me AR aging for client X"
5. Manual test: "What's the GL detail for account 1000?"

---

## 4. Phase 1: AccountingAgent + Evidence Ledger

**Goal:** Replace ReviewAgent with AccountingAgent that has investigation capabilities and records reasoning steps.

**Timeline:** 2-3 weeks  
**Risk:** Medium  
**New code:** ~800 lines  
**New MCP tools:** 3 (evidence ledger)

### 4.1 AccountingAgent Implementation

**New file:** `src/backend/v4/magentic_agents/accounting_agent.py`

This is NOT a new class — it's the same `FoundryAgentTemplate` with a new system prompt and config entry. The `MagenticAgentFactory` already supports arbitrary agent names via the team JSON config.

**Team config change:**

```json
{
  "agents": [
    {
      "name": "AccountingAgent",
      "deployment_name": "gpt-4.1",
      "description": "Senior accounting analyst for balance sheet reviews, variance investigation, and data queries",
      "system_message": "<<see Section 8.1>>",
      "use_mcp": true,
      "use_reasoning": false,
      "use_rag": false,
      "use_bing": false,
      "coding_tools": false
    },
    {
      "name": "ProxyAgent",
      "deployment_name": "",
      "use_mcp": false,
      "use_reasoning": false,
      "use_rag": false,
      "use_bing": false,
      "coding_tools": false
    }
  ]
}
```

### 4.2 Evidence Ledger — Backend Models

**New file:** `src/backend/common/models/evidence_ledger.py`

```python
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
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class EvidenceLedger:
    ledger_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    client_id: str = ""
    period_end: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    entries: list[EvidenceLedgerEntry] = field(default_factory=list)

    def add_entry(self, entry: EvidenceLedgerEntry) -> None:
        entry.run_id = self.run_id
        self.entries.append(entry)

    def get_hypothesis_chain(self, hypothesis_id: str) -> list[EvidenceLedgerEntry]:
        """Get a hypothesis and all evidence that tested it."""
        return [
            e
            for e in self.entries
            if e.entry_id == hypothesis_id or e.parent_entry_id == hypothesis_id
        ]

    def to_audit_trail(self) -> str:
        """Render as human-readable audit trail."""
        lines = [f"# Evidence Ledger — Run {self.run_id}", ""]
        for e in self.entries:
            prefix = {"hypothesis": "💡", "tool_call": "🔧", "evidence": "📊",
                       "conclusion": "✅", "escalation": "⚠️",
                       "correction_applied": "📝"}.get(e.step_type, "•")
            conf = f" (confidence: {e.confidence:.0%})" if e.confidence else ""
            lines.append(f"{prefix} [{e.timestamp[:19]}] {e.content}{conf}")
            if e.tool_name:
                lines.append(f"   Tool: {e.tool_name}")
            if e.tool_output_summary:
                lines.append(f"   Result: {e.tool_output_summary[:200]}")
            lines.append("")

        return "\n".join(lines)

    def to_cosmos_doc(self, session_id: str) -> dict:
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
```

### 4.3 Evidence Ledger — MCP Tools

**3 new tools** in `src/mcp_server/services/finance_service.py`:

```python
@mcp.tool()
async def log_evidence_entry(
    run_id: str,
    step_type: str,
    content: str,
    tool_name: str | None = None,
    tool_input_summary: str | None = None,
    tool_output_summary: str | None = None,
    confidence: float | None = None,
    parent_entry_id: str | None = None,
) -> str:
    """Log a reasoning step to the evidence ledger for a balance sheet review run.
    Used by the AccountingAgent to record hypotheses, tool calls, evidence, 
    conclusions, and escalations during investigation."""
    # POST /api/reviews/balance-sheet/{run_id}/evidence-ledger
    ...

@mcp.tool()
async def get_evidence_ledger(run_id: str) -> str:
    """Retrieve the full evidence ledger (audit trail) for a review run."""
    # GET /api/reviews/balance-sheet/{run_id}/evidence-ledger
    ...

@mcp.tool()
async def get_evidence_summary(run_id: str) -> str:
    """Get a summarized evidence ledger (conclusions only) for a review run."""
    # GET /api/reviews/balance-sheet/{run_id}/evidence-ledger?summary=true
    ...
```

### 4.4 Evidence Ledger — Backend API

**2 new endpoints** in `src/backend/api/reviews.py`:

```python
@router.post("/balance-sheet/{run_id}/evidence-ledger")
async def add_evidence_entry(run_id: str, entry: EvidenceLedgerEntryRequest):
    """Add a reasoning step to the evidence ledger."""
    ...

@router.get("/balance-sheet/{run_id}/evidence-ledger")
async def get_evidence_ledger(run_id: str, summary: bool = False):
    """Retrieve evidence ledger for a run."""
    ...
```

### 4.5 Response Handlers Update

**File:** `src/backend/v4/callbacks/response_handlers.py`

Add `AccountingAgent` to the friendly name map:

```python
_INTERNAL_NAME_MAP: dict[str, str] = {
    # ... existing entries ...
    "AccountingAgent": "Accounting Analyst",
}
```

### 4.6 Context Budgeting Utility

**New file:** `src/backend/common/utils/context_budget.py`

```python
"""Token-aware context truncation for agent prompts."""

import json
from typing import Any

# Rough estimate: 1 token ≈ 3.5 characters for English text
CHARS_PER_TOKEN = 3.5


def truncate_tool_output(output: str, max_tokens: int = 4000) -> str:
    """Truncate tool output to fit within token budget."""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(output) <= max_chars:
        return output

    # Try to parse as JSON array and truncate items
    try:
        data = json.loads(output)
        if isinstance(data, list) and len(data) > 0:
            # Keep items until we approach the budget
            kept = []
            current_len = 2  # []
            for item in data:
                item_str = json.dumps(item)
                if current_len + len(item_str) + 2 > max_chars - 100:
                    break
                kept.append(item)
                current_len += len(item_str) + 2
            remaining = len(data) - len(kept)
            result = json.dumps(kept, indent=None)
            if remaining > 0:
                result = result[:-1] + f', "{remaining} more items omitted"]'
            return result
        elif isinstance(data, dict):
            # For dicts, serialize and truncate
            output = json.dumps(data, indent=None)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: character truncation
    return output[:max_chars] + f"\n\n[... truncated, {len(output) - max_chars} chars omitted]"


def budget_corrections(corrections: list[dict], max_tokens: int = 1000) -> str:
    """Format corrections within token budget."""
    if not corrections:
        return ""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    lines = ["## Prior Corrections for This Client"]
    current_len = len(lines[0])

    for c in corrections[:5]:  # Max 5 corrections
        line = (
            f"- [{c.get('created_at', 'unknown')[:10]}] "
            f"Rule {c.get('rule_id', 'general')}: "
            f'"{c.get("user_correction", "")}" '
            f"(Type: {c.get('correction_type', 'general')}, "
            f"Active: {'yes' if c.get('active', True) else 'no'})"
        )
        if current_len + len(line) > max_chars:
            break
        lines.append(line)
        current_len += len(line)

    return "\n".join(lines)
```

### 4.7 Files Changed (Phase 1 Summary)

| File | Change Type | Lines |
|---|---|---|
| `data/agent_teams/balance_sheet_review_team.json` | Modified | ~80 |
| `src/backend/v4/orchestration/human_approval_manager.py` | Modified | ~60 |
| `src/backend/v4/callbacks/response_handlers.py` | Modified | ~5 |
| `src/backend/common/models/evidence_ledger.py` | **New** | ~120 |
| `src/backend/common/utils/context_budget.py` | **New** | ~80 |
| `src/backend/api/reviews.py` | Modified | ~60 |
| `src/mcp_server/services/finance_service.py` | Modified | ~80 |
| `src/backend/tests/test_evidence_ledger.py` | **New** | ~100 |
| `src/backend/tests/test_context_budget.py` | **New** | ~80 |

**Total new code:** ~665 lines (including tests)

---

## 5. Phase 2: Correction Memory

**Goal:** Store user corrections per client/rule. Surface them as context, never silently apply.

**Timeline:** 2 weeks  
**Risk:** Low-Medium  
**New code:** ~600 lines  
**New MCP tools:** 3

### 5.1 Correction Store

**New file:** `src/backend/common/database/correction_store.py`

```python
"""Per-client correction memory — stores user feedback for contextual retrieval."""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from common.database.cosmos_util import get_cosmos_container_client


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
    """Save a correction to Cosmos DB."""
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
    return doc


def get_corrections(
    client_id: str,
    *,
    rule_id: str | None = None,
    active_only: bool = True,
    max_results: int = 10,
) -> list[dict]:
    """Retrieve corrections for a client, optionally filtered by rule."""
    container = get_cosmos_container_client()
    conditions = [
        "c.data_type = 'correction'",
        "c.client_id = @client_id",
    ]
    params = [{"name": "@client_id", "value": client_id}]

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
    return list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))


def deactivate_correction(correction_id: str, session_id: str = "corrections") -> bool:
    """Soft-delete a correction."""
    container = get_cosmos_container_client()
    try:
        doc = container.read_item(item=correction_id, partition_key=session_id)
        doc["active"] = False
        container.upsert_item(doc)
        return True
    except Exception:
        return False


def increment_applied(correction_id: str, session_id: str = "corrections") -> None:
    """Track that a correction was used in a review."""
    container = get_cosmos_container_client()
    try:
        doc = container.read_item(item=correction_id, partition_key=session_id)
        doc["times_applied"] = doc.get("times_applied", 0) + 1
        doc["last_applied_at"] = datetime.now(timezone.utc).isoformat()
        container.upsert_item(doc)
    except Exception:
        pass  # Non-critical — don't fail the review
```

### 5.2 Correction MCP Tools

**3 new tools** in `src/mcp_server/services/finance_service.py`:

```python
@mcp.tool()
async def store_correction(
    client_id: str,
    user_correction: str,
    correction_type: str,
    rule_id: str | None = None,
    account_ref: str | None = None,
    original_output: str = "",
    reasoning: str = "",
) -> str:
    """Store a user correction for a specific client. Corrections are retrieved
    automatically in future reviews to provide context. Types: classification,
    threshold, ignore, procedure, general."""
    # POST /api/reviews/corrections
    ...

@mcp.tool()
async def retrieve_corrections(
    client_id: str,
    rule_id: str | None = None,
    max_results: int = 5,
) -> str:
    """Retrieve stored corrections for a client. Used before generating 
    explanations to incorporate prior feedback."""
    # GET /api/reviews/corrections?client_id=X&rule_id=Y
    ...

@mcp.tool()
async def deactivate_correction(correction_id: str) -> str:
    """Deactivate a correction that is no longer applicable."""
    # DELETE /api/reviews/corrections/{correction_id}
    ...
```

### 5.3 Correction API Endpoints

**3 new endpoints** in `src/backend/api/reviews.py`:

```python
@router.post("/corrections")
async def create_correction(correction: CorrectionRequest):
    """Store a user correction."""
    ...

@router.get("/corrections")
async def list_corrections(
    client_id: str,
    rule_id: str | None = None,
    active_only: bool = True,
    max_results: int = 10,
):
    """List corrections for a client."""
    ...

@router.delete("/corrections/{correction_id}")
async def remove_correction(correction_id: str):
    """Soft-delete a correction."""
    ...
```

### 5.4 Integration into AccountingAgent Workflow

The AccountingAgent's system prompt instructs it to call `retrieve_corrections(client_id)` as the FIRST step of any review workflow, before interpreting rule results. The retrieved corrections are injected as context via the prompt pattern described in ADR-005.

### 5.5 Files Changed (Phase 2 Summary)

| File | Change Type | Lines |
|---|---|---|
| `src/backend/common/database/correction_store.py` | **New** | ~120 |
| `src/backend/api/reviews.py` | Modified | ~60 |
| `src/mcp_server/services/finance_service.py` | Modified | ~60 |
| `data/agent_teams/balance_sheet_review_team.json` | Modified | ~20 (prompt update) |
| `src/backend/tests/test_correction_store.py` | **New** | ~100 |
| `src/tests/mcp_server/test_correction_tools.py` | **New** | ~80 |

**Total new code:** ~440 lines (including tests)

---

## 6. Phase 3: Data Query Mode + PrepAgent

**Goal:** Enable ad-hoc data queries ("show me AP aging") and MER narrative generation.

**Timeline:** 3-4 weeks  
**Risk:** Medium  
**New code:** ~500 lines  
**New MCP tools:** 2

### 6.1 Data Query Mode

Already partially supported by Phase 0 (expanded system prompt + `tool_choice=auto`). Phase 3 adds:

1. **Intent classification in plan prompt** — distinguish "run review" vs "query data" vs "generate narrative"
2. **Targeted tool routing** — for data queries, pattern is: identify tool → call with parameters → format response → done (no investigation loop)

### 6.2 PrepAgent

**Purpose:** Generates human-readable MER narratives, variance commentary, and work paper text.

**Why separate from AccountingAgent:**
- Different output style (prose vs. structured JSON/tables)
- Different temperature setting (0.3 for writing quality vs. 0.1 for analytical accuracy)
- Different prompt focus (writing craft vs. accounting reasoning)
- Can be called AFTER AccountingAgent completes analysis

**Team config addition:**

```json
{
  "name": "PrepAgent",
  "deployment_name": "gpt-4.1",
  "description": "MER narrative writer — generates variance commentary, account explanations, and work paper text from review results",
  "system_message": "<<see Section 8.3>>",
  "use_mcp": true,
  "use_reasoning": false,
  "use_rag": false,
  "use_bing": false,
  "coding_tools": false
}
```

### 6.3 MER Narrative MCP Tools

```python
@mcp.tool()
async def generate_mer_narrative(
    run_id: str,
    sections: list[str] | None = None,
    style: str = "concise",
) -> str:
    """Generate MER narrative commentary from review results. Sections can include:
    executive_summary, variance_commentary, account_notes, action_items, 
    management_discussion. Style: concise, detailed, or executive."""
    # POST /api/reviews/balance-sheet/{run_id}/narrative
    ...

@mcp.tool()
async def generate_variance_commentary(
    run_id: str,
    account_ref: str | None = None,
    threshold_pct: float = 10.0,
) -> str:
    """Generate variance commentary for accounts that changed significantly 
    between periods. Optionally filter to a specific account."""
    # POST /api/reviews/balance-sheet/{run_id}/variance-commentary
    ...
```

### 6.4 Files Changed (Phase 3 Summary)

| File | Change Type | Lines |
|---|---|---|
| `data/agent_teams/balance_sheet_review_team.json` | Modified | ~50 (add PrepAgent) |
| `src/backend/v4/orchestration/human_approval_manager.py` | Modified | ~30 (workflow templates) |
| `src/backend/v4/callbacks/response_handlers.py` | Modified | ~3 (PrepAgent name) |
| `src/backend/api/reviews.py` | Modified | ~100 (narrative endpoints) |
| `src/mcp_server/services/finance_service.py` | Modified | ~80 (narrative tools) |
| `src/backend/tests/test_narrative.py` | **New** | ~100 |

**Total new code:** ~363 lines (including tests)

---

## 7. Phase 4: RAG Knowledge Base

**Goal:** Enable retrieval of accounting policies, prior MERs, SOPs, and audit notes.

**Timeline:** 2-3 weeks  
**Risk:** Low (infrastructure already exists — `use_rag=true` + Azure AI Search is configured)

### 7.1 What to Index

| Document Type | Source | Index Strategy |
|---|---|---|
| Prior MER reports | Blob Storage | Per-section chunking (executive summary, account notes, findings) |
| Accounting policies | Drive | Full-document indexing |
| Client SOPs | Drive | Section-level chunks |
| Rule specifications | `docs/rules/balance_sheet/` | Per-rule doc |
| Evidence ledger summaries | Cosmos DB | Conclusion entries from past runs |

### 7.2 Implementation

1. Create Azure AI Search index: `mer-knowledge-base`
2. Build indexer pipeline: `src/backend/pipelines/knowledge_indexer.py`
3. Enable `use_rag=true` + `index_name="mer-knowledge-base"` for AccountingAgent
4. Update system prompt to instruct RAG retrieval behavior

### 7.3 Agent Config Change

```json
{
  "name": "AccountingAgent",
  "use_rag": true,
  "index_name": "mer-knowledge-base"
}
```

**Note:** Enabling RAG changes the agent from MCP mode to Azure Search mode in `foundry_agent.py`. This is mutually exclusive with MCP tools currently. To use BOTH RAG and MCP tools, we need to modify `_after_open()` to support hybrid mode — this is the main engineering task for Phase 4.

---

## 8. Agent System Prompts

### 8.1 AccountingAgent — Full System Prompt

```
You are a Senior Accounting Analyst performing month-end balance sheet reviews, variance investigations, and financial data analysis. You interface with QBO (QuickBooks Online), Google Drive, and the rules engine via MCP tools.

## PROFESSIONAL MINDSET
- You are conservative in conclusions. Prefer "needs investigation" over unsupported claims.
- You distinguish between facts (data from tools) and interpretations (your analysis).
- You quantify uncertainty: "likely" (>75%), "possibly" (50-75%), "uncertain" (<50%).
- You cite specific data points: account name, dollar amount, date, transaction ID.
- You NEVER state a cause without evidence from a tool call.
- Accountability > completeness — flag for review rather than dismiss.
- When two explanations are equally plausible, present both and recommend which to investigate first.

## OPERATING MODES

### MODE 1: FULL REVIEW
When user requests a balance sheet review:
1. Call retrieve_corrections(client_id) to load any prior corrections for this client
2. Call qbo_connection_status(client_id) — if disconnected, return connect URL and STOP
3. Call get_or_create_balance_sheet_review(client_id, period_end) — this runs the deterministic rules pipeline (25-45s)
4. Review rule results. For any FAIL or NEEDS_REVIEW result:
   a. Log a hypothesis via log_evidence_entry(step_type="hypothesis")
   b. Pull supporting data (qbo_get_gl_detail, qbo_get_transactions_by_account, etc.)
   c. Log evidence via log_evidence_entry(step_type="evidence")
   d. Form a conclusion via log_evidence_entry(step_type="conclusion")
5. Check corrections — if a prior correction applies, note it alongside the rule result
6. Return structured JSON with findings, evidence ledger summary, and recommendations

### MODE 2: INVESTIGATE
When user asks about a specific finding, variance, or account:
1. Load prior run data via get_balance_sheet_review(run_id)
2. Form 2-3 hypotheses for the variance
3. Test each hypothesis:
   - Pull GL detail for the account (qbo_get_gl_detail)
   - Check transaction history (qbo_get_transactions_by_account)
   - Compare to prior periods (via balance_sheet data)
   - Check aging if relevant (qbo_get_ar_aging, qbo_get_ap_aging)
4. Log each step to evidence ledger
5. Select best-supported explanation
6. Return: finding, hypotheses tested, evidence, conclusion, confidence level

### MODE 3: DATA QUERY
When user asks for specific financial data (not a full review):
1. Identify the appropriate QBO tool to call
2. Call the tool with correct parameters
3. Format the response clearly
4. No investigation needed — just data retrieval and presentation

### MODE 4: FOLLOW-UP
When user asks a follow-up about a previous review:
1. Load prior run via get_balance_sheet_review(run_id from context)
2. Answer from existing data if possible
3. If additional data is needed, drill into specific accounts

### MODE 5: CORRECTION
When user corrects a finding or provides feedback:
1. Acknowledge the correction
2. Store via store_correction(client_id, user_correction, correction_type, ...)
3. Confirm what was stored
4. Explain how this will affect future reviews

### MODE 6: EXPLAIN
When user asks for explanation of an accounting concept, rule, or finding:
1. Retrieve relevant context (prior run, rule spec, corrections)
2. Explain in clear accounting terms
3. Reference specific data points from the review

## STOP CONDITIONS — Escalate to ProxyAgent when:
1. Two hypotheses have equal evidence (ambiguous — ask human)
2. Required data unavailable (tool error or empty)
3. Variance exceeds 300% of threshold (too large for automated analysis)
4. Investigation has used 6+ tool calls without conclusion
5. Finding involves potential fraud indicators
6. Regulatory/tax implications requiring professional judgment

When escalating:
- State what was investigated
- What was found
- Why escalation is needed
- Specific questions for the reviewer

## HALLUCINATION GUARDRAIL
1. Rule results: report EXACTLY as returned. Do not add, remove, modify, or re-evaluate any rule status.
2. Financial data: report numbers EXACTLY as returned by tools. Do not round, adjust, or estimate.
3. Evidence: every claim MUST cite a specific tool call result.
4. Uncertainty: if unsure, say so. Never fabricate explanations.

## TOOL INVENTORY (35 tools available)

### Review Pipeline
- qbo_connection_status — check if QBO is connected for a client
- run_balance_sheet_review — trigger a new review (prefer get_or_create for idempotency)
- get_or_create_balance_sheet_review — idempotent: reuse existing or create new review
- get_balance_sheet_review — retrieve results of a completed review
- start_balance_sheet_review — start a review (returns immediately, poll for status)
- wait_for_balance_sheet_review — poll a running review until completion

### QBO Data Queries
- qbo_get_trial_balance — trial balance for a period
- qbo_get_balance_sheet — balance sheet report as of a date
- qbo_get_profit_and_loss — P&L for a date range
- qbo_get_cash_flow — cash flow statement
- qbo_get_gl_detail — general ledger detail (filterable by account, vendor, customer, amount)
- qbo_get_transactions_by_account — all transactions for a specific account
- qbo_get_transaction — individual transaction detail
- qbo_list_accounts — chart of accounts
- qbo_get_ar_aging — accounts receivable aging summary
- qbo_get_ap_aging — accounts payable aging summary
- qbo_get_open_invoices — open/unpaid invoices
- qbo_get_open_bills — open/unpaid bills
- qbo_get_bank_reconciliation_status — bank reconciliation status
- qbo_get_sales_tax_liability — sales tax liability report
- qbo_get_sales_tax_returns — sales tax returns
- qbo_get_payroll_liabilities — payroll liabilities

### Evidence & Documents
- drive_connection_status — check Google Drive connection
- drive_list_files — list files in Drive
- drive_get_file — retrieve file content
- drive_get_evidence_manifest — get evidence requirements manifest

### Snapshots & Artifacts
- list_snapshots — list data snapshots for a run
- get_snapshot — retrieve a snapshot
- get_artifact — retrieve an artifact

### Layered Pipeline (advanced)
- bs_fetch_data — fetch raw QBO data only
- bs_normalize_data — normalize fetched data
- bs_list_rules — list available rules
- bs_run_rules — run specific rules against normalized data
- bs_get_findings — get findings from a completed run
- bs_submit_evidence_request — submit evidence for HITL review

### Evidence Ledger
- log_evidence_entry — record a reasoning step
- get_evidence_ledger — retrieve full audit trail
- get_evidence_summary — get conclusions summary

### Corrections
- store_correction — save a user correction
- retrieve_corrections — get prior corrections for context
- deactivate_correction — remove an outdated correction

## OUTPUT FORMAT
Return structured JSON for all responses. The orchestrator handles formatting for the user.
For errors: {"status": "error", "error": "<message>"}
For QBO disconnected: {"status": "qbo_disconnected", "connect_url": "<url>", "client_id": "<id>"}
```

### 8.2 ProxyAgent — System Prompt

*(Unchanged — empty system_message, no model, no tools. Functions as human relay.)*

### 8.3 PrepAgent — System Prompt (Phase 3)

```
You are a Financial Report Writer specializing in month-end review narratives. You transform review data into clear, professional accounting commentary.

## YOUR ROLE
You receive analyzed review data from AccountingAgent and generate:
- Executive summaries
- Per-account variance commentary  
- Management discussion narratives
- Work paper notes
- Action item lists with priority ordering

## WRITING STANDARDS
- Use professional accounting language appropriate for a CPA audience
- Be specific: reference account names, dollar amounts, percentages, dates
- Structure: finding → cause → impact → recommendation
- Format variance commentary as: "Account X [increased/decreased] by $Y (Z%) from prior period, 
  [driven by / due to] [specific cause]. [Recommended action]."
- Use active voice
- Keep sentences under 25 words where possible
- Bold key figures and account names

## OUTPUT FORMATS
- `executive_summary`: 3-5 paragraphs covering financial position, key concerns, notable changes
- `variance_commentary`: Per-account notes for variances exceeding threshold
- `account_notes`: Detailed notes per account section (Bank, AR, AP, etc.)
- `action_items`: Numbered list with urgency levels and assigned parties
- `management_discussion`: Narrative suitable for management/board review

## TOOLS
- generate_mer_narrative(run_id, sections, style) — your primary tool
- generate_variance_commentary(run_id, account_ref, threshold_pct) — per-account commentary
- get_balance_sheet_review(run_id) — retrieve review data
- get_evidence_ledger(run_id) — retrieve reasoning audit trail
- retrieve_corrections(client_id) — check for client-specific context
```

### 8.4 Orchestrator Plan Prompt Expansion

**Updated `plan_append` in `human_approval_manager.py`:**

```python
plan_append = """

IMPORTANT: Never ask the user for information or clarification until all agents on the team have been asked first.

Plan steps should always include a bullet point, followed by an agent name, followed by a description of the action to be taken. If a step involves multiple actions, separate them into distinct steps with an agent included in each step. The first plan step must always be a MagenticManager orchestration step that states it will coordinate the team. Every plan step MUST start with the assigned agent name in bold.

## WORKFLOW TEMPLATES — Select based on user intent:

### TEMPLATE 1: FULL_REVIEW
Triggered by: "Run balance sheet review", "Review client X for period Y"
1. **MagenticManager** — Coordinate balance sheet review workflow
2. **AccountingAgent** — Check QBO connection, run or retrieve review, investigate findings, log evidence
3. **MagenticManager** — Compile final report from AccountingAgent results

### TEMPLATE 2: INVESTIGATE
Triggered by: "Why did X fail?", "Investigate variance in Y", "What caused Z?"
1. **MagenticManager** — Coordinate investigation workflow
2. **AccountingAgent** — Load prior run, form hypotheses, gather evidence, reach conclusion
3. **MagenticManager** — Present investigation findings

### TEMPLATE 3: DATA_QUERY
Triggered by: "Show me AR aging", "What's the trial balance?", "List accounts"
1. **MagenticManager** — Coordinate data query
2. **AccountingAgent** — Call appropriate QBO data tool, format response
3. **MagenticManager** — Present data

### TEMPLATE 4: FOLLOW_UP
Triggered by: Follow-up questions in same session about a prior review
1. **MagenticManager** — Coordinate follow-up
2. **AccountingAgent** — Load prior run, answer from existing data or drill deeper
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

## CRITICAL RULES
- AccountingAgent is called AT MOST TWICE per workflow (once for primary task, once for follow-up if needed)
- If AccountingAgent reports QBO disconnected, terminate immediately with connect URL
- For transient failures, retry up to 2 times before escalating via ProxyAgent
- For follow-ups, AccountingAgent uses existing run_id — do NOT trigger a new review
- ProxyAgent is used ONLY when human input is explicitly needed (escalation, ambiguous correction, missing info)
"""
```

---

## 9. New MCP Tools Specification

### Complete Tool Inventory (v2)

| # | Tool | Phase | Type |
|---|---|---|---|
| 1-35 | *(existing 35 tools)* | v1 | Existing |
| 36 | `log_evidence_entry` | 1 | New |
| 37 | `get_evidence_ledger` | 1 | New |
| 38 | `get_evidence_summary` | 1 | New |
| 39 | `store_correction` | 2 | New |
| 40 | `retrieve_corrections` | 2 | New |
| 41 | `deactivate_correction` | 2 | New |
| 42 | `generate_mer_narrative` | 3 | New |
| 43 | `generate_variance_commentary` | 3 | New |

**Total v2 tools: 43**

---

## 10. Cost & Latency Projections

### Per-Review Cost

| Phase | LLM Calls | Input Tokens | Output Tokens | Est. Cost | Latency |
|---|---|---|---|---|---|
| v1 (current) | 2-3 | ~8K | ~2K | $0.02-0.05 | 35-65s |
| Phase 0 | 3-5 | ~15K | ~4K | $0.05-0.15 | 45-90s |
| Phase 1 (investigate) | 5-10 | ~25K | ~6K | $0.10-0.30 | 60-120s |
| Phase 2 (corrections) | 6-12 | ~28K | ~7K | $0.12-0.35 | 65-130s |
| Phase 3 (narrative) | 8-15 | ~35K | ~10K | $0.18-0.50 | 80-150s |

**Monthly cost projection (50 clients, 1 review each):**
- v1: $1-2.50/month
- Full v2: $9-25/month

### Latency Breakdown

| Operation | Duration | Notes |
|---|---|---|
| QBO connection check | 1-3s | Network round-trip |
| Balance sheet review pipeline | 25-45s | QBO API calls + rules engine |
| GL detail per account | 2-5s | QBO API |
| Investigation per finding | 10-20s | 2-4 tool calls + reasoning |
| Evidence ledger write | <100ms | Cosmos write |
| Correction retrieval | <200ms | Cosmos query |
| Final answer generation | 3-8s | LLM output |

### Cost Control Mechanisms

1. **Max tool calls per workflow:** 12 (configurable)
2. **Context budgeting:** 24K token ceiling (ADR-006)
3. **Investigation depth limit:** 6 tool calls per finding before escalation (ADR-008)
4. **Template-based routing:** prevents unconstrained planning (ADR-002)

---

## 11. Risk Register

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Agent hallucinates accounting explanations | Medium | High | Hallucination guardrail in prompt + evidence requirement |
| R2 | Token cost explosion on complex reviews | Low | Medium | Context budgeting (ADR-006) + max tool calls |
| R3 | Corrections contradict each other | Medium | Low | Expiry dates + surface as context, don't silently apply |
| R4 | Investigation loops (agent never reaches conclusion) | Medium | Medium | Stop conditions (ADR-008) + 6-call limit |
| R5 | Context window overflow on data-heavy clients | Low | High | `truncate_tool_output()` utility + per-category budgets |
| R6 | Regression in simple review quality | Low | High | Keep v1 flow as fallback template + comprehensive tests |
| R7 | Latency increase makes UX worse | Medium | Medium | WebSocket streaming shows progress + investigation steps |
| R8 | Multi-agent coordination bugs (Phase 3) | Medium | Medium | Validate single-agent (Phase 0-2) before adding PrepAgent |

---

## 12. Success Metrics

### Phase 0 Success Criteria
- [ ] Agent can answer "Show me AR aging for client X" without running a full review
- [ ] Agent can answer "What's the GL detail for account 1000?" directly
- [ ] Full review still works correctly (no regression)
- [ ] All existing tests pass

### Phase 1 Success Criteria
- [ ] For FAIL findings, agent automatically pulls supporting data and explains cause
- [ ] Evidence ledger is persisted in Cosmos for every investigation
- [ ] Investigation latency < 120s for 80% of reviews
- [ ] Agent escalates when it can't determine cause (stop conditions work)

### Phase 2 Success Criteria
- [ ] User can say "That's wrong, these are retainers" and correction is stored
- [ ] On next review, agent surfaces the correction alongside the rule result
- [ ] Corrections expire after 12 months
- [ ] Corrections are client-specific (don't leak to other clients)

### Phase 3 Success Criteria
- [ ] PrepAgent generates professional MER narrative commentary
- [ ] Variance commentary references specific accounts and amounts
- [ ] Narrative quality is acceptable to a CPA reviewer

### Phase 4 Success Criteria
- [ ] Agent can reference prior MERs when answering questions
- [ ] Accounting policies are retrieved and applied in explanations
- [ ] RAG works alongside MCP tools (hybrid mode)

---

## 13. Testing Strategy

### Unit Tests (per phase)

| Phase | Test File | What It Tests |
|---|---|---|
| 0 | `test_tool_choice.py` | Verify `_mcp_tool_choice()` returns `"auto"` by default |
| 1 | `test_evidence_ledger.py` | EvidenceLedger CRUD, audit trail rendering, Cosmos serialization |
| 1 | `test_context_budget.py` | `truncate_tool_output()` for JSON arrays, dicts, text |
| 2 | `test_correction_store.py` | Correction CRUD, expiry, deactivation, client isolation |
| 2 | `test_correction_tools.py` | MCP tool endpoints for corrections |
| 3 | `test_narrative.py` | Narrative generation endpoints |

### Integration Tests

| Test | What It Validates |
|---|---|
| Full review end-to-end | AccountingAgent runs review, investigates findings, produces evidence ledger |
| Correction round-trip | Store correction → next review surfaces it in context |
| Data query routing | User asks "show AR aging" → agent calls correct tool → returns data |
| Escalation trigger | Agent hits stop condition → escalates to ProxyAgent |

### Regression Guard

All existing tests must pass after every phase. Run:
```bash
cd src/backend && uv run pytest --tb=short -q
cd src/frontend && npm run build
```

---

## Appendix A: File Change Map (All Phases)

| File | Ph.0 | Ph.1 | Ph.2 | Ph.3 | Ph.4 |
|---|---|---|---|---|---|
| `balance_sheet_review_team.json` | ✏️ | ✏️ | ✏️ | ✏️ | ✏️ |
| `foundry_agent.py` | ✏️ | — | — | — | ✏️ |
| `human_approval_manager.py` | ✏️ | ✏️ | — | ✏️ | — |
| `response_handlers.py` | — | ✏️ | — | ✏️ | — |
| `reviews.py` | — | ✏️ | ✏️ | ✏️ | — |
| `finance_service.py` | — | ✏️ | ✏️ | ✏️ | — |
| `evidence_ledger.py` | — | 🆕 | — | — | — |
| `context_budget.py` | — | 🆕 | — | — | — |
| `correction_store.py` | — | — | 🆕 | — | — |
| `knowledge_indexer.py` | — | — | — | — | 🆕 |
| Tests | ✅ | 🆕 | 🆕 | 🆕 | 🆕 |

Legend: ✏️ = modified, 🆕 = new file, — = no change, ✅ = verify existing

---

## Appendix B: Comparison — Prior Proposal vs. This Spec

| Dimension | Prior Proposal | This Spec | Reason |
|---|---|---|---|
| Agent count | 6 agents | 3 agents (Phase 0-2: 2) | ADR-001: merge Analyst+Investigator |
| Planning | Free-form LLM planner | 6 constrained templates | ADR-002: prevent planning drift |
| Rules interaction | LLM can "suggest rules" | LLM interprets, never evaluates | ADR-003: audit safety |
| Corrections | Silent application | Surfaced as context | ADR-005: transparency |
| Investigation depth | Unbounded | 6-call limit + stop conditions | ADR-008: cost control |
| Context management | Not addressed | Token budgeting per category | ADR-006: prevent degradation |
| Phase 0 | "Change tool_choice" | tool_choice + prompt + templates | All 3 needed together |
| New tools needed | 7 | 8 (3 ledger + 3 correction + 2 narrative) | Evidence ledger added |
| Fine-tuning | "Phase 5" | Not in scope | ADR: reasoning via environment, not training |

---

## Appendix C: Devil's Advocate Final Assessment

### What could still go wrong

1. **The expanded system prompt may be too long.** At ~2,500 tokens, it's manageable. But if we add RAG context + corrections + investigation instructions in a single turn, we approach 4K of system-level content. Monitor prompt token usage in production.

2. **GPT-4.1 may not reliably follow the 6 workflow templates.** The Magentic orchestrator's plan prompt is already complex. Adding 6 templates increases the chance of misrouting. **Counter:** The templates are well-structured and the plan prompt uses clear trigger phrases. Test extensively.

3. **Evidence Ledger creates write amplification.** Every hypothesis, tool call, and conclusion is a Cosmos write. For a 10-finding investigation, that's ~30 writes. At $0.00005/write, it's $0.0015 per review — negligible, but the latency adds up (30 × 50ms = 1.5s). **Counter:** Batch writes at end of investigation, not per-entry.

4. **Correction memory creates a management burden.** Who reviews expired corrections? Who resolves conflicts? **Counter:** Start with auto-expiry (12 months) and review reports. Add management UI in Phase 5 if needed.

5. **The "3 agents max" constraint may be too conservative.** If PrepAgent proves valuable, users will want more specialization. **Counter:** This is intentional. Prove each agent before adding more. The architecture supports N agents — we're constraining the timeline, not the capability.

### What this spec gets right

1. **Phase 0 is brilliant.** Zero code, maximum learning. You'll know within 24 hours whether the expanded-capability approach works.
2. **Evidence Ledger is the highest-value novel addition.** No competing system does this well. It's your moat.
3. **Corrections as context, not overrides** is the correct architectural choice for regulated industries.
4. **Context budgeting prevents the failure mode that kills 90% of RAG-augmented agents.**
5. **Stop conditions + escalation is underrated.** This is what makes the difference between a demo and a production system.
