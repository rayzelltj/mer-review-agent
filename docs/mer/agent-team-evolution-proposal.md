# Agent Team Evolution Proposal

> **Status:** SUPERSEDED by [v2-implementation-spec.md](v2-implementation-spec.md) and [architecture-decision-record.md](architecture-decision-record.md)  
> **Author:** Architecture Review (2026-03-02)  
> **Goal:** Evolve from deterministic MER reviewer → autonomous accounting analyst  
> **Note:** This was the initial proposal. The reviewed & approved specification is in [v2-implementation-spec.md](v2-implementation-spec.md). Key differences: 3 agents instead of 6 (ADR-001), constrained planning instead of free-form (ADR-002), corrections surfaced not applied (ADR-005).  

---

## Current State (v1 — Deployed)

```
User
  ↓
Orchestrator (HumanApprovalMagenticManager)
  ↓
ReviewAgent (gpt-4.1, MCP tools, monolithic pipeline)
  ↓
ProxyAgent (human clarification, no model)
```

**What it does today:**
- ReviewAgent calls `run_balance_sheet_review` — one synchronous API call (~25-45s)
- Pipeline internally: fetch QBO data → normalize via adapters → run 24 deterministic rules → build balance sheet view
- Orchestrator generates markdown executive summary from ReviewAgent's JSON output  
- ProxyAgent relays clarification questions to user

**What it does NOT do:**
- Investigate variances (WHY did revenue increase 40%?)
- Query data dynamically (drill into GL detail, transactions, specific accounts)
- Learn from corrections (user says "that's a retainer, not overdue" → forgotten next run)
- Prepare MER narratives (per-account commentary, variance explanations)
- Search prior MERs or accounting policies for context
- Form hypotheses and test them with data
- Explain its reasoning in accounting terms

**Assets already built but unused:**
- 33 MCP tools registered (ReviewAgent uses 2-3)
- 16 direct QBO query tools (`qbo_get_trial_balance`, `qbo_get_gl_detail`, `qbo_get_transactions_by_account`, `qbo_get_ar_aging`, etc.)
- Layered pipeline tools (`bs_fetch_data`, `bs_normalize_data`, `bs_run_rules`)
- Drive evidence tools (`drive_list_files`, `drive_get_file`)
- Snapshot/artifact retrieval tools
- Azure AI Search infrastructure (used by other teams, idle for MER)

---

## Target State (v2 — Accounting Reasoning System)

### Design Principles

1. **Rules stay deterministic.** The rules engine is the most reliable component. Never let an LLM decide rule outcomes. LLM agents investigate, explain, and prepare — rules evaluate.
2. **Tools create intelligence.** An LLM without tools is a chatbot. An LLM with 33 financial query tools, memory retrieval, and investigation workflows is an analyst.
3. **Memory without retraining.** Corrections, client heuristics, and prior MERs are stored in vector/document DB and retrieved into context — the model appears to learn without fine-tuning.
4. **Narrow agents > one super agent.** Each agent has a focused role, specific tools, and an optimized system prompt. The orchestrator plans and routes.
5. **Accounting principles are encoded in prompts, not model weights.** Materiality, variance thresholds, accrual logic, reconciliation — all injected via system prompts and RAG.

---

## Proposed Agent Team (v2)

```
User
  ↓
Orchestrator (PlannerAgent — replaces rigid routing with LLM-generated task plans)
  ↓
┌─────────────────────────────────────────────────────────────────┐
│  Specialized Accounting Agents                                   │
│                                                                  │
│  1. AnalystAgent     — runs review pipeline + interprets results │
│  2. InvestigatorAgent — drills into variances + forms hypotheses │
│  3. DataAgent         — queries connected systems dynamically    │
│  4. MemoryAgent       — retrieves/stores corrections & context   │
│  5. PrepAgent         — generates MER narratives & work papers   │
│  6. ProxyAgent        — human clarification (exists today)       │
└─────────────────────────────────────────────────────────────────┘
  ↓
Connected Systems (via MCP tools)
  - QBO (16 query tools + review pipeline)
  - Google Drive (evidence files)
  - Memory Store (Cosmos DB corrections + Azure AI Search RAG)
  - Prior MERs (blob storage snapshots)
```

---

### Agent Specifications

#### 1. AnalystAgent (evolves from current ReviewAgent)

**Role:** Senior accountant performing the month-end review. Runs the deterministic pipeline, interprets results, identifies items needing investigation.

**Model:** `gpt-4.1` (reasoning mode)

**MCP Tools:**
- `run_balance_sheet_review` — full pipeline
- `get_balance_sheet_review` — retrieve prior results
- `bs_list_rules` — list available rules
- `bs_get_findings` — get findings for a run

**System Prompt (core):**
```
You are a Senior Accounting Analyst performing month-end balance sheet reviews.

CAPABILITIES:
- Run the deterministic balance sheet review pipeline
- Interpret rule results (PASS/FAIL/WARN/NEEDS_REVIEW)
- Identify items requiring investigation by InvestigatorAgent
- Assess materiality of findings

ACCOUNTING PRINCIPLES you apply:
- Materiality: variances below $X or Y% are immaterial (per client config)
- Reconciliation: book balance must agree to subledger/statement within tolerance
- Completeness: all expected accounts must be present
- Cutoff: transactions recorded in correct period

WHEN A RULE FAILS OR WARNS:
1. State the finding clearly
2. Assess materiality (is this significant?)
3. Flag for InvestigatorAgent if cause is unknown
4. Recommend specific action if cause is obvious

HALLUCINATION GUARDRAIL: Report rule results exactly as returned. 
Do not modify, re-evaluate, or override any rule status.
```

**Key behavior change from v1:** Instead of just returning raw JSON, the AnalystAgent interprets results and decides whether to escalate findings to the InvestigatorAgent.

---

#### 2. InvestigatorAgent (NEW — the magic agent)

**Role:** Variance investigator. When the AnalystAgent identifies an anomaly, the InvestigatorAgent drills in to find the root cause.

**Model:** `gpt-4.1` (reasoning mode)

**MCP Tools:**
- `qbo_get_gl_detail` — general ledger transaction detail
- `qbo_get_transactions_by_account` — account-level transaction list
- `qbo_get_trial_balance` — trial balance for period comparison
- `qbo_get_balance_sheet` — balance sheet for multi-period comparison
- `qbo_get_profit_and_loss` — P&L for revenue/expense analysis
- `qbo_get_ar_aging` / `qbo_get_ap_aging` — aging detail
- `qbo_get_open_invoices` / `qbo_get_open_bills` — open items
- `qbo_get_transaction` — single transaction detail
- `get_snapshot` / `get_artifact` — prior period data
- `drive_list_files` / `drive_get_file` — supporting documents

**System Prompt (core):**
```
You are an Accounting Investigator. Your job is to determine WHY 
a balance or variance exists, not just that it exists.

INVESTIGATION PROTOCOL:
1. Receive finding from AnalystAgent (rule failure, variance, anomaly)
2. Form 2-3 hypotheses for the cause
3. For each hypothesis, identify which data would confirm or refute it
4. Call the appropriate tools to gather evidence
5. Select the most supported explanation
6. Report: cause, evidence, confidence level, recommended action

HYPOTHESIS EXAMPLES:
- Large balance change: seasonality? large transaction? reclassification? error?
- Aging items: disputed? retainer? timing? forgotten?
- Reconciliation gap: outstanding items? posting error? cutoff issue?

EVIDENCE REQUIREMENTS:
- Every claim must cite specific transaction(s), account(s), or document(s)
- Include the tool call that produced the evidence
- State confidence: HIGH (data confirms), MEDIUM (likely but not certain), LOW (hypothesis only)

NEVER:
- State a cause without evidence from a tool call
- Guess transaction amounts or dates
- Assume causation from correlation alone
```

**Key capability:** This agent transforms the system from "flag it" to "explain it." It answers the question every reviewer asks: "Why?"

---

#### 3. DataAgent (NEW)

**Role:** Data retrieval specialist. Pulls specific data from connected systems on request. Used by other agents (especially InvestigatorAgent) and directly by the user for ad-hoc queries.

**Model:** `gpt-4.1`

**MCP Tools:** ALL 33 tools (full access)

**System Prompt (core):**
```
You are a Financial Data Retrieval Specialist. You query connected 
accounting systems and return structured, accurate data.

CONNECTED SYSTEMS:
- QuickBooks Online (QBO): balance sheet, P&L, trial balance, GL detail,
  accounts, aging, transactions, invoices, bills, tax, payroll, bank recon
- Google Drive: bank statements, supporting documents, working papers
- Review History: prior run snapshots and artifacts

QUERY PRINCIPLES:
- Always use the most specific tool available
- For transaction-level detail, use qbo_get_gl_detail or qbo_get_transactions_by_account
- For account summaries, use the appropriate report tool
- Return data in the format requested — do not summarize unless asked
- If a query returns too many results, suggest filtering parameters

NEVER:
- Modify data (you are read-only)
- Fabricate data points
- Return partial data without noting what's missing
```

**Key capability:** Other agents delegate data retrieval to DataAgent, keeping their own context windows clean. Users can also query it directly: "Show me all transactions over $10k in the Cash account for January."

---

#### 4. MemoryAgent (NEW — learning system)

**Role:** Manages persistent memory across sessions. Stores corrections, retrieves prior context, maintains client-specific heuristics.

**Model:** `gpt-4.1`

**Backend Services (new, not MCP):**
- Cosmos DB: `correction_memory` collection — stores user corrections per client/rule
- Azure AI Search: `accounting_knowledge` index — accounting policies, SOPs, prior MER narratives
- Blob Storage: prior run snapshots for historical comparison

**New MCP Tools needed:**
- `store_correction(client_id, rule_id, context, correction, reasoning)` — persist a user correction
- `retrieve_corrections(client_id, rule_ids?)` — get relevant corrections for a client
- `search_knowledge(query, client_id?)` — semantic search over accounting knowledge base
- `store_client_heuristic(client_id, heuristic, source)` — persist a client-specific rule
- `retrieve_prior_mer(client_id, period)` — get prior month's review results

**System Prompt (core):**
```
You are the Memory and Learning Agent. You manage the system's 
institutional knowledge about clients and accounting practices.

MEMORY TYPES:
1. CORRECTIONS: When a user says "that's wrong" or overrides a finding,
   store the pattern, correction, and reasoning. Retrieve on future runs.
2. CLIENT HEURISTICS: Client-specific rules (e.g., "ignore FX < $5k",
   "marketing is seasonal Q4", "AP retainers are normal for this vendor").
3. ACCOUNTING KNOWLEDGE: Policies, SOPs, standards, audit notes.
4. HISTORICAL CONTEXT: Prior MER results for trend comparison.

CORRECTION LIFECYCLE:
- Corrections have a created_date and optional expiry_date
- Corrections can be deactivated (user changes their mind)
- On conflict (contradictory corrections), surface both and ask user

RETRIEVAL PROTOCOL:
- Before each review run, retrieve all active corrections for the client
- Inject corrections as context for AnalystAgent and InvestigatorAgent
- Format: "Prior correction (2026-01): [rule_id] — [correction text]"

NEVER:
- Silently override rule outcomes (corrections are CONTEXT, not overrides)
- Delete corrections without user consent
- Apply one client's corrections to another client
```

**Data Model (Cosmos DB):**
```json
{
    "id": "corr-uuid",
    "client_id": "acme-corp",
    "rule_id": "BS-AP-AR-ITEMS-OLDER-60",
    "pattern": "AP items tagged as retainers",
    "original_output": "FAIL: 3 items older than 60 days",
    "user_correction": "These are retainers, not overdue. Expected for this client.",
    "correction_type": "client_heuristic",
    "created_at": "2026-01-31T00:00:00Z",
    "expiry_date": null,
    "active": true,
    "source": "user_feedback"
}
```

**Key capability:** This is the "it learns" mechanism. Not model retraining — retrieval-augmented behavior modification.

---

#### 5. PrepAgent (NEW — MER preparation)

**Role:** Generates MER narratives, variance commentaries, and draft work papers. Transforms structured rule results into accountant-ready output.

**Model:** `gpt-4.1`

**MCP Tools:**
- `get_balance_sheet_review` — review results
- `bs_get_findings` — detailed findings
- `get_snapshot` / `get_artifact` — historical data
- `qbo_get_balance_sheet` — multi-period comparison
- `qbo_get_profit_and_loss` — P&L for commentary

**New MCP Tools needed:**
- `generate_mer_narrative(run_id)` → per-account commentary from rule results + data
- `generate_variance_commentary(account_id, run_id)` → explain period-over-period change
- `export_mer_package(run_id, format)` → fill Google Sheets template (MVP2)

**System Prompt (core):**
```
You are an MER Preparation Specialist. You generate professional 
month-end review narratives that junior accountants would prepare.

OUTPUT FORMATS:
1. ACCOUNT COMMENTARY: Per-account narrative explaining balance,
   changes from prior period, rule results, and action items.
2. VARIANCE ANALYSIS: Period-over-period comparison with explanations.
3. EXECUTIVE SUMMARY: 3-5 paragraph overview for the reviewer.
4. WORK PAPER NOTES: Supporting calculations and assumptions.

WRITING STYLE:
- Professional, concise, factual
- Every statement backed by data (cite account numbers, amounts, dates)
- Use accounting terminology correctly
- Flag uncertainties explicitly ("requires further investigation")
- Never speculate without evidence

EXAMPLE ACCOUNT COMMENTARY:
"Cash and Cash Equivalents — $245,892 (prior: $198,341, Δ+24%)
 Status: PASS (all 3 bank accounts reconciled through 2026-01-31)
 The increase of $47,551 is primarily driven by a large customer 
 payment received on 2026-01-28 ($42,000, Inv #1234 from Acme Corp).
 No unreconciled items. No action required."
```

**Key capability:** This is the "MER preparer replacement." Instead of a human writing per-account commentary, the PrepAgent drafts it from structured data.

---

#### 6. ProxyAgent (exists today — unchanged)

**Role:** Human-in-the-loop clarification. Relays questions to user via WebSocket.

**Model:** None  
**Tools:** None  
**Change from v1:** None

---

### Orchestrator Evolution

The current `HumanApprovalMagenticManager` does round-robin routing with a fixed plan template. For v2, the orchestrator becomes a true planner.

**Current behavior:**
```
Fixed plan: "ReviewAgent will run the balance sheet review"
→ Route to ReviewAgent
→ Format final answer
```

**v2 behavior:**
```
User: "Run balance sheet review for Acme Corp, Jan 2026"
→ PlannerAgent generates:
  1. MemoryAgent: Retrieve corrections and prior context for Acme Corp
  2. AnalystAgent: Run balance sheet review pipeline
  3. InvestigatorAgent: Investigate any FAIL/WARN findings
  4. PrepAgent: Generate executive summary and account commentary
→ Execute plan, stream results

User: "Why did accounts receivable increase so much?"
→ PlannerAgent generates:
  1. DataAgent: Pull AR aging detail + transaction list for current and prior period
  2. InvestigatorAgent: Analyze the data and identify the cause
→ Execute, respond

User: "That's actually a retainer, not overdue"
→ PlannerAgent generates:
  1. MemoryAgent: Store correction (client=Acme, rule=BS-AP-AR-ITEMS-OLDER-60, correction=retainer)
→ Execute, confirm stored
```

**Implementation:** Modify the orchestrator plan prompt in `human_approval_manager.py` to support flexible multi-agent routing based on intent classification.

---

## Tool Inventory (v2)

### Existing Tools (33 — no new backend code needed)

| Category | Tools | Primary Agent |
|---|---|---|
| Review Pipeline | `run_balance_sheet_review`, `get_balance_sheet_review`, `start_balance_sheet_review`, `get_or_create_balance_sheet_review`, `wait_for_balance_sheet_review` | AnalystAgent |
| Layered Pipeline | `bs_fetch_data`, `bs_normalize_data`, `bs_run_rules`, `bs_get_findings`, `bs_list_rules`, `bs_submit_evidence_request` | AnalystAgent |
| QBO Reports | `qbo_get_balance_sheet`, `qbo_get_profit_and_loss`, `qbo_get_cash_flow`, `qbo_get_trial_balance` | DataAgent, InvestigatorAgent |
| QBO Detail | `qbo_get_gl_detail`, `qbo_get_transactions_by_account`, `qbo_get_transaction`, `qbo_list_accounts` | InvestigatorAgent, DataAgent |
| QBO Aging/Tax | `qbo_get_ar_aging`, `qbo_get_ap_aging`, `qbo_get_open_invoices`, `qbo_get_open_bills`, `qbo_get_bank_reconciliation_status`, `qbo_get_sales_tax_liability`, `qbo_get_sales_tax_returns`, `qbo_get_payroll_liabilities` | InvestigatorAgent, DataAgent |
| Drive | `drive_connection_status`, `drive_list_files`, `drive_get_file`, `drive_get_evidence_manifest` | DataAgent |
| Snapshots | `list_snapshots`, `get_snapshot`, `get_artifact` | DataAgent, PrepAgent |
| Connection | `qbo_connection_status` | AnalystAgent |

### New Tools Needed (7)

| Tool | Backend Endpoint | Agent | Priority |
|---|---|---|---|
| `store_correction` | `POST /api/memory/corrections` | MemoryAgent | P1 |
| `retrieve_corrections` | `GET /api/memory/corrections?client_id=X` | MemoryAgent | P1 |
| `search_knowledge` | `POST /api/memory/search` | MemoryAgent | P2 |
| `store_client_heuristic` | `POST /api/memory/heuristics` | MemoryAgent | P2 |
| `retrieve_prior_mer` | `GET /api/reviews/balance-sheet/find?client_id=X&period=Y` | MemoryAgent | P1 (partially exists) |
| `generate_mer_narrative` | `POST /api/reviews/balance-sheet/{run_id}/narrative` | PrepAgent | P2 |
| `generate_variance_commentary` | `POST /api/reviews/balance-sheet/{run_id}/variance/{account_id}` | PrepAgent | P3 |

---

## Team Config (v2)

```json
{
    "name": "Balance Sheet Review Team",
    "deployment_name": "gpt-4.1",
    "description": "Autonomous accounting analyst for month-end balance sheet reviews",
    "agents": [
        {
            "name": "AnalystAgent",
            "deployment_name": "gpt-4.1",
            "use_mcp": true,
            "use_reasoning": true,
            "description": "Senior accountant — runs review pipeline, interprets results"
        },
        {
            "name": "InvestigatorAgent",
            "deployment_name": "gpt-4.1",
            "use_mcp": true,
            "use_reasoning": true,
            "description": "Variance investigator — drills into anomalies, forms hypotheses"
        },
        {
            "name": "DataAgent",
            "deployment_name": "gpt-4.1",
            "use_mcp": true,
            "use_reasoning": false,
            "description": "Data retrieval specialist — queries QBO, Drive, snapshots"
        },
        {
            "name": "MemoryAgent",
            "deployment_name": "gpt-4.1",
            "use_mcp": true,
            "use_reasoning": false,
            "description": "Learning system — stores corrections, retrieves prior context"
        },
        {
            "name": "PrepAgent",
            "deployment_name": "gpt-4.1",
            "use_mcp": true,
            "use_reasoning": true,
            "description": "MER preparer — generates narratives, variance commentary"
        },
        {
            "name": "ProxyAgent"
        }
    ]
}
```

---

## Implementation Phases

### Phase 0: Quick Win (1 day, no new code)

**Change `tool_choice` from `"required"` to `"auto"`** in `foundry_agent.py` so the agent can reason between tool calls.

**Expand ReviewAgent system prompt** to teach it about all 33 tools and accounting principles. This alone unlocks investigation capability within the current single-agent setup.

**Why:** Proves the concept without any new agents, tools, or backend code. If the ReviewAgent can successfully use `qbo_get_gl_detail` to investigate a failed rule, the architecture works.

### Phase 1: AnalystAgent + InvestigatorAgent (2-3 weeks)

- Rename ReviewAgent → AnalystAgent
- Add InvestigatorAgent with investigation-focused system prompt
- Update orchestrator plan prompt for 2-agent routing
- Test: Run review → AnalystAgent finds FAIL → InvestigatorAgent drills in → explains cause
- No new backend code needed (uses existing 33 tools)

### Phase 2: MemoryAgent + Correction Storage (2-3 weeks)

- New Cosmos DB collection: `correction_memory`
- New backend API: `POST/GET /api/memory/corrections`
- New MCP tools: `store_correction`, `retrieve_corrections`
- Add MemoryAgent to team config
- Update orchestrator to retrieve corrections before each run
- Test: User corrects a finding → stored → retrieved on next run → injected as context

### Phase 3: DataAgent + Ad-hoc Queries (1-2 weeks)

- Add DataAgent to team config (uses all existing tools)
- Update orchestrator plan prompt for data query intent routing
- Test: "Show me all transactions over $5k in Cash for January" → DataAgent queries → returns data

### Phase 4: PrepAgent + MER Narratives (3-4 weeks)

- New backend endpoint: `POST /api/reviews/balance-sheet/{run_id}/narrative`
- New MCP tool: `generate_mer_narrative`
- Add PrepAgent to team config
- Test: After review completes → PrepAgent generates per-account commentary

### Phase 5: RAG Knowledge Base (2-3 weeks)

- Populate Azure AI Search with: accounting policies, SOPs, prior MER narratives
- New MCP tool: `search_knowledge`
- Update MemoryAgent to search before investigations
- Test: Agent retrieves relevant policy when explaining a finding

---

## Cost & Latency Projections

### v1 (Current)
| Metric | Value |
|---|---|
| LLM calls per review | ~2 (plan + final answer) |
| Token cost per review | ~$0.02-0.05 |
| End-to-end latency | ~35-65s |
| Agent cold-start | ~5-10s (1 agent) |

### v2 (Projected)
| Metric | Value |
|---|---|
| LLM calls per review | ~8-15 (plan + 4-5 agents × 1-3 calls each) |
| Token cost per review | ~$0.10-0.50 |
| End-to-end latency | ~60-120s (investigation adds time) |
| Agent cold-start | ~15-25s (5 agents) |

**Mitigation:** Agent persistence in Azure AI Foundry (reuse agent IDs across sessions, already partially implemented via Cosmos caching). Cap `max_round_count` per agent.

---

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hallucinates accounting conclusions | HIGH | HIGH | Evidence-citation requirement in all prompts. Rules engine stays deterministic. |
| Token cost overrun | MEDIUM | MEDIUM | Per-session token budget. `max_round_count` caps. Monitor via OpenTelemetry. |
| Agent coordination failures | MEDIUM | MEDIUM | Start with Phase 0 (single agent), prove it works, then decompose. Fallback to v1 behavior if orchestration fails. |
| Correction memory conflicts | LOW | MEDIUM | Corrections are context-only (never override rules). Expiry dates. User review dashboard. |
| Multi-agent latency | HIGH | LOW | Users tolerate 60-120s for deep analysis if they see streaming progress. Add phase-level status updates. |

---

## Success Metrics

| Metric | v1 Baseline | v2 Target |
|---|---|---|
| Rules executed per review | 24 deterministic | 24 deterministic + N investigative queries |
| Findings with explanations | 0% (just PASS/FAIL) | 80%+ of FAIL/WARN findings have root cause |
| User corrections persisted | 0 | 100% of explicit corrections stored & retrieved |
| Follow-up questions answered | Limited (re-run only) | Ad-hoc data queries, variance explanations, context questions |
| MER narrative drafts | 0 | Generated for every review run |
| Time to first useful output | ~35-65s | ~20s (streaming partial results) |

---

## Not In Scope (Explicitly Deferred)

- **Fine-tuning or custom model training** — use foundation models (GPT-4.1) with prompt engineering + RAG
- **P&L review rules** — separate specification needed (MVP3)
- **Multi-currency support** — requires new adapters
- **External system connectors beyond QBO/Drive** — Dext, Plooto, Karbon are future
- **Bulk review runs** — single-client focus first
- **Client onboarding self-service** — admin-managed for now
