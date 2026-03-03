# Architecture Decision Record: MER Agent Evolution

> **Status:** ACCEPTED — implementation-ready  
> **Date:** 2026-03-02  
> **Author:** Architecture Review Board (SWE + Architect + Devil's Advocate + Product)  
> **Supersedes:** `agent-team-evolution-proposal.md` (draft, partially incorrect)

---

## ADR-001: Merge AnalystAgent + InvestigatorAgent into Single AccountingAgent

### Context

The prior proposal split analysis and investigation into two agents. The architecture review raised a critical objection: **investigation IS analysis continuation** — premature decomposition creates coordination overhead, context loss, and silent reasoning gaps.

### Decision

**Phase 1-2 uses a single `AccountingAgent`** with two operating modes:
- `review` mode: Run pipeline, interpret results, assess materiality
- `investigate` mode: Drill into variances, form hypotheses, validate with data

Split into separate agents ONLY if prompt length exceeds 8K tokens OR investigation latency exceeds 90s consistently.

### Consequences

- **Pro:** Single agent retains full context across analysis → investigation transition
- **Pro:** 60% fewer inter-agent coordination bugs
- **Pro:** One prompt to maintain, test, and iterate on
- **Con:** Single point of failure — if AccountingAgent halluccinates, no second agent catches it
- **Mitigation:** Evidence Ledger (ADR-004) provides auditability; rules engine remains deterministic

---

## ADR-002: Constrained Planner, Not Free-Form Planner

### Context

The initial proposal suggested a PlannerAgent that generates workflows dynamically. Devil's Advocate flagged: **unconstrained planning is the #1 cause of agent system unreliability in production.** GPT-4.1 will confidently generate plausible but wrong execution plans.

### Decision

**Replace free-form planning with slot-filling over predefined workflow templates.**

The orchestrator selects from 6 workflow templates based on intent classification, then fills slots. It does NOT invent novel workflows.

```
WORKFLOW TEMPLATES:
1. FULL_REVIEW     → check_qbo → get_or_create_review → interpret → report
2. INVESTIGATE     → load_prior_run → identify_target → pull_data → hypothesize → validate → explain
3. DATA_QUERY      → identify_data_need → call_qbo_tool → format_response
4. FOLLOW_UP       → load_prior_run → answer_from_context_or_drill
5. CORRECTION      → parse_correction → validate → store → confirm
6. EXPLAIN         → load_context → generate_explanation
```

The HumanApprovalMagenticManager's plan prompt already constrains routing — we extend this pattern rather than replacing it.

### Consequences

- **Pro:** Deterministic workflow selection — auditable, testable, debuggable
- **Pro:** Prevents cost explosions from runaway planning (max tool calls per workflow is bounded)
- **Pro:** Each template has known latency characteristics
- **Con:** Less flexible for edge-case queries outside the 6 templates
- **Mitigation:** Template 3 (DATA_QUERY) handles ad-hoc queries; template 4 (FOLLOW_UP) is catch-all

---

## ADR-003: Rules Engine Stays Deterministic — LLM Interprets, Never Evaluates

### Context

This is the most critical architectural boundary in the system. The rules engine has 23 implemented rules, each with defined inputs, outputs, tests, and evidence requirements. The temptation is to let the LLM "enhance" rule evaluation with reasoning.

### Decision

**The rules engine is a sealed subsystem.** The LLM:
- CAN read rule results
- CAN explain why a rule passed/failed in accounting terms
- CAN recommend actions based on results
- CAN suggest which rules to run (via `rule_ids` filter)
- CANNOT modify pass/fail determinations
- CANNOT add new rules at runtime
- CANNOT skip rules
- CANNOT override rule severity

The LLM's role is interpretation and explanation — never judgment on accounting correctness.

### Consequences

- **Pro:** Audit trail is deterministic and reproducible
- **Pro:** Regulators can validate rule logic independently from LLM behavior
- **Pro:** Rule failures are testable with pytest (already true — 23 rules have tests)
- **Con:** LLM cannot apply soft judgment (e.g., "this variance is immaterial given the client's industry")
- **Mitigation:** Client-specific overrides via `ClientRulesConfig` (already exists) and correction memory (ADR-005)

---

## ADR-004: Evidence Ledger — Structured Reasoning Audit Trail

### Context

The architecture review identified a missing capability: the system produces conclusions but doesn't record HOW it reached them. Junior accountants show their work. The AI must too.

### Decision

**Add an Evidence Ledger** that records every reasoning step during an investigation.

```python
@dataclass
class EvidenceLedgerEntry:
    entry_id: str              # uuid
    run_id: str                # links to balance_sheet_run
    timestamp: datetime
    agent: str                 # which agent produced this
    step_type: str             # "hypothesis" | "tool_call" | "evidence" | "conclusion" | "escalation"
    content: str               # human-readable description
    tool_name: str | None      # MCP tool called, if applicable
    tool_input: dict | None    # tool parameters (PII-scrubbed)
    tool_output_summary: str | None  # truncated output (max 500 chars)
    confidence: float | None   # 0.0-1.0, agent self-assessment
    parent_entry_id: str | None  # links hypothesis to evidence that tested it

@dataclass
class EvidenceLedger:
    run_id: str
    entries: list[EvidenceLedgerEntry]
    
    def get_hypothesis_chain(self, hypothesis_id: str) -> list[EvidenceLedgerEntry]:
        """Get a hypothesis and all evidence entries that tested it."""
        ...
    
    def to_audit_trail(self) -> str:
        """Render as human-readable audit trail document."""
        ...
```

Stored in Cosmos DB as `data_type="evidence_ledger"`, partitioned by `session_id`.

### Consequences

- **Pro:** Complete auditability — every claim traces back to evidence
- **Pro:** Debugging tool — when the agent gives wrong answers, trace the reasoning
- **Pro:** Training data — ledger entries become future fine-tuning candidates
- **Pro:** Client-facing artifact — auditors can review the AI's work papers
- **Con:** Storage cost: ~2-5KB per investigation, negligible
- **Con:** Adds 50-100ms per entry write — mitigated by batching

---

## ADR-005: Correction Memory — Per-Client, Expiring, Surfaced Not Applied

### Context

The user's core requirement: "if it does something wrong, I can tell it and it learns." The architecture review raised 4 risks with naive correction storage:
1. Corrections are client-specific but rules are global
2. Corrections can contradict over time
3. Accounting policies change — corrections need expiry
4. Silent overrides are audit-dangerous

### Decision

**Corrections are stored but SURFACED as context, never silently applied.**

```python
@dataclass
class CorrectionRecord:
    correction_id: str         # uuid
    client_id: str
    rule_id: str | None        # if correction applies to a specific rule
    account_ref: str | None    # if correction applies to a specific account
    original_output: str       # what the agent said
    user_correction: str       # what the user said was correct
    correction_type: str       # "classification" | "threshold" | "ignore" | "procedure" | "general"
    reasoning: str             # why the user made this correction
    created_at: datetime
    created_by: str            # user_id
    expires_at: datetime | None  # optional TTL (default: 12 months)
    active: bool               # soft delete
    times_applied: int         # tracking
    last_applied_at: datetime | None
```

**Retrieval protocol:** Before generating explanations or recommendations:
1. Query corrections for `(client_id, rule_id)` — max 5 most recent active corrections
2. Inject into agent context as:
```
## Prior Corrections for This Client
- [2026-01-15] Rule BS-AP-AR-ITEMS-OLDER-60: "These 3 items are retainers, not overdue. 
  Do not flag as past due." (Type: classification, Active: yes)
- [2025-12-01] Rule BS-CLEARING-ACCOUNTS-ZERO: "Marketing clearing account is expected 
  to carry a balance during Q4 due to seasonal campaigns." (Type: ignore, Active: yes)
```

**The agent sees corrections but the rule engine does NOT.** Rules still produce deterministic PASS/FAIL. The agent then contextualizes: "Rule BS-AP-AR-ITEMS-OLDER-60 flagged FAIL. Note: user previously classified these as retainers (Jan 2026). Recommended action: verify retainer status is still current, then override if confirmed."

### Consequences

- **Pro:** Learning without audit risk — corrections are visible, never hidden
- **Pro:** Expiry prevents stale corrections from persisting forever
- **Pro:** Client-specific — corrections don't leak across clients
- **Pro:** Human always sees both the raw rule result AND the correction context
- **Con:** More verbose output (rule result + correction note + recommendation)
- **Con:** User must re-confirm corrections periodically (by design — accounting policies change)

---

## ADR-006: Context Budgeting — Prevent Token Explosion

### Context

An investigative agent that pulls GL detail for 30 accounts will consume 50K+ tokens of raw financial data. GPT-4.1 has a 128K context window but reasoning quality degrades significantly beyond ~30K tokens of structured data.

### Decision

**Enforce per-category token budgets in the system prompt:**

| Context Category | Max Tokens | Strategy |
|---|---|---|
| System prompt | 3,000 | Fixed |
| Corrections | 1,000 | Top 5 most recent, truncated |
| Prior MER context | 2,000 | Summarized, not raw |
| Tool results (per call) | 4,000 | Truncate to top-N rows + summary |
| Investigation data | 8,000 | Agent must summarize between tool calls |
| Conversation history | 6,000 | Sliding window |
| **Total budget** | **24,000** | Leaves 104K for model reasoning |

**Implementation:** Add a `truncate_tool_output(output: str, max_tokens: int = 4000) -> str` utility that:
1. If output fits, return as-is
2. If output is JSON array, keep first N items + `"... and {remaining} more items"`
3. If output is text, keep first `max_tokens * 3` chars (rough token estimate) + `"[truncated]"`

### Consequences

- **Pro:** Prevents reasoning degradation from context overflow
- **Pro:** Predictable token costs per investigation
- **Con:** Agent may miss important data in truncated results
- **Mitigation:** Agent can make follow-up tool calls with filters to drill into specific items

---

## ADR-007: `tool_choice="auto"` — Unlock Multi-Tool Reasoning

### Context

Currently `foundry_agent.py` defaults `tool_choice` to `"required"`, forcing the agent to call a tool on EVERY turn. This prevents the agent from:
- Reasoning about tool results between calls
- Deciding NOT to call a tool when it already has enough info
- Generating a final answer without a gratuitous tool call

### Decision

**Change default `tool_choice` to `"auto"` for MCP agents.**

Implementation: Set env var `MCP_TOOL_CHOICE_REQUIRED=false` or modify `_mcp_tool_choice()` default.

### Consequences

- **Pro:** Agent can reason between tool calls — critical for investigation workflows
- **Pro:** Reduces unnecessary tool calls (cost/latency savings)
- **Pro:** Zero code change — just env var or 1-line change
- **Con:** Agent may "overthink" and not call tools when it should
- **Mitigation:** System prompt explicitly instructs: "Always verify claims with tool calls. Never state a cause without citing evidence from a tool."

---

## ADR-008: Escalation Model — Know When to Stop

### Context

The architecture review identified a gap: the system assumes infinite investigation. Junior accountants know when to stop and escalate. Without stop conditions, agents over-reason, waste tokens, and produce increasingly speculative conclusions.

### Decision

**Add explicit stop conditions to investigation prompts:**

```
STOP CONDITIONS — Escalate to human when:
1. Two hypotheses have equal evidence support (ambiguous)
2. Required data is unavailable (tool returned error or empty)
3. Variance exceeds 3x the investigation threshold (too large for automated analysis)
4. Investigation has used 6+ tool calls without reaching a conclusion
5. Finding involves potential fraud indicators (unusual parties, round amounts, backdated entries)
6. Regulatory or tax implications that require professional judgment

When escalating, provide:
- What was investigated
- What was found
- Why escalation is needed
- Specific questions for the human reviewer
```

### Consequences

- **Pro:** Prevents runaway investigations
- **Pro:** Builds trust — users know the AI knows its limits
- **Pro:** Reduces token cost on ambiguous cases
- **Con:** Some investigations that could succeed get escalated
- **Mitigation:** Tune thresholds based on feedback data

---

## ADR-009: Accounting Personality — Professional Conservative Mindset

### Context

The architecture review identified that prompts define tasks but not professional mindset. An accounting AI that sounds confident about speculative conclusions erodes trust faster than one that admits uncertainty.

### Decision

**Add an "Accounting Personality" section to every agent system prompt:**

```
PROFESSIONAL MINDSET:
- You are conservative in conclusions. Prefer "needs investigation" over unsupported claims.
- You distinguish between facts (data from tools) and interpretations (your analysis).
- You quantify uncertainty: "likely" (>75% confidence), "possibly" (50-75%), "uncertain" (<50%).
- You cite specific data points for every claim: account name, dollar amount, date, transaction ID.
- You never state a cause without evidence from a tool call.
- Accountability is more important than completeness — it's better to flag something for review 
  than to dismiss it incorrectly.
- When two explanations are equally plausible, present both and recommend which to investigate first.
```

### Consequences

- **Pro:** Dramatically increases trust from accounting professionals
- **Pro:** Reduces hallucination impact (hedged claims are safer than confident wrong ones)
- **Con:** More verbose output
- **Mitigation:** Keep personality section to ~200 tokens

---

## ADR-010: Phase 0 Quick Win — Maximum Impact, Zero New Code

### Context

The system currently has 35 MCP tools but the ReviewAgent only uses 2-3. The fastest way to increase capability is to let the existing agent USE the existing tools.

### Decision

**Phase 0 consists of exactly 3 changes:**

1. Set `MCP_TOOL_CHOICE_REQUIRED=false` (env var) OR change default in `_mcp_tool_choice()` to `"auto"`
2. Expand ReviewAgent `system_message` in `balance_sheet_review_team.json` to teach it about all 35 tools, accounting principles, investigation workflows, and the professional mindset
3. Expand `plan_append` in `human_approval_manager.py` to support the 6 workflow templates

**No new backend code. No new tools. No new agents. No new infrastructure.**

### Consequences

- **Pro:** Testable in 1 day
- **Pro:** Validates the core hypothesis (agent + existing tools = analyst)
- **Pro:** Reversible — just revert the config/prompt if it doesn't work
- **Con:** Single agent may struggle with long investigations (context limitations)
- **Mitigation:** Phase 1 adds the AccountingAgent with proper context budgeting

