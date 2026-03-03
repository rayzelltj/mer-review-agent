# System Overview — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified in code unless otherwise tagged

---

## What Is the MER Review Agent?

The MER (Month-End Report) Review Agent is a **Reviewer Copilot** — not a reviewer replacement — built on the Multi-Agent Custom Automation Engine (MACAE) platform. It automates the mechanical parts of month-end financial review for accounting firms and internal finance teams.

✅ *Verified in code:* `docs/architecture/mer-review-agent-spec.md` §2

### What It Does

- **Connects to QuickBooks Online (QBO)** to pull balance sheet data, aging reports, account lists, and transaction details for a given client and period-end date.
- **Runs a deterministic rules engine** (26 balance sheet rules as of this writing) that checks reconciliation, zero-balance, subledger match, aging, tax filing, and evidence-match conditions.
- **Produces structured, auditable review results** with per-account status (`PASS`, `FAIL`, `WARN`, `NEEDS_REVIEW`, `NOT_APPLICABLE`) and supporting evidence references.
- **Presents a multi-period balance sheet view** (current + 3 prior months) with rule hit details.
- **Supports chat continuity** — follow-up questions in the same session can reference run artifacts and findings.
- **Requests missing evidence** via a Human-in-the-Loop (HITL) agent when required data is unavailable.

### What It Does NOT Do

- **Does not replace professional judgment** — it flags findings and surfaces data; humans make the final call.
- **Does not generate free-form audit conclusions** — the rules engine is deterministic and its outputs are explainable.
- **Does not handle P&L review rules** (planned for MVP3).
- **Does not directly access external systems from the frontend** — all privileged operations are server-side.
- **Does not support mobile-native clients**.

✅ *Verified in code:* `docs/architecture/mer-review-agent-spec.md` §3, §4

---

## High-Level Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                        User (Reviewer)                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Sign in (Microsoft Entra ID / EasyAuth)                     │
│  2. Connect QBO for selected client (OAuth popup)               │
│  3. Select client + month-end period                            │
│  4. Submit "Run balance sheet review" task                      │
│  5. Approve generated plan (human-in-the-loop)                  │
│  6. Agents execute: connect → normalize → rules → report        │
│  7. View results: multi-period BS + status per account/rule     │
│  8. Ask follow-up questions in same chat thread                 │
│  9. (Future) Export MER Review Package to Google Sheets          │
└─────────────────────────────────────────────────────────────────┘
```

### Agent Execution Sequence (Balance Sheet Review Team)

The Balance Sheet Review Team (`data/agent_teams/balance_sheet_review_team.json`) defines 6 agents that execute in sequence:

| Order | Agent | Role |
|---|---|---|
| 1 | **ConnectorAgent** | Parses review context, checks QBO connection, creates/retrieves balance sheet review run |
| 2 | **NormalizationAgent** | Retrieves review run, lists snapshots, returns snapshot/artifact keys |
| 3 | **RulesAgent** | Extracts findings from run, returns pass/fail/needs_review counts + critical rule IDs |
| 4 | **ReportAgent** | Builds executive summary with balance_sheet_rows, key findings, next actions |
| 5 | **HITLAgent** | Collects missing evidence requests, deduplicates, provides connect URLs |
| 6 | **ProxyAgent** | Coordinates agent handoffs (no MCP tools) |

✅ *Verified in code:* `data/agent_teams/balance_sheet_review_team.json`

---

## Key Design Goals

| Goal | How It's Achieved |
|---|---|
| **Consistency** | Deterministic rules engine — same inputs always produce the same result |
| **Speed** | Automated data pull + parallel rule evaluation reduces review from hours to minutes |
| **Auditability** | Every finding cites evidence references, rule IDs, and human-readable explanations |
| **Human-in-the-loop** | Plan approval before execution; HITL agent for missing evidence; chat follow-ups |
| **Explainability** | Structured `RuleResult` output with status, severity, summary, details, and evidence_used |
| **Least privilege** | Secrets stay server-side; OAuth tokens in Cosmos DB; frontend never sees API keys |
| **Extensibility** | Rules are decorator-registered; adapters are pure functions; team configs are JSON |

---

## MVP Phases

✅ *Verified in code:* `docs/architecture/mer-review-agent-spec.md` §4

| Phase | Scope | Status |
|---|---|---|
| **MVP1** | QBO connector, balance sheet rules only, deterministic engine, web UI with 4 periods, chat continuity | ✅ Current |
| **MVP2** | Google Drive connector for supporting documents, MER Review Package export to Google Sheets | 🔍 Planned |
| **MVP3** | Profit & Loss review rules | 🔍 Planned |

---

## Platform Context

The MER Review Agent is one of six agent teams on the MACAE platform:

| Team | Purpose |
|---|---|
| **Balance Sheet Review** | MER review (this document) |
| Retail Customer Success | Customer satisfaction analysis (RAG-based) |
| Human Resources | Employee onboarding simulation |
| Product Marketing | Press release / content generation |
| RFP Analysis | RFP response review (RAG-based) |
| Contract Compliance | Contract NDA review (RAG-based) |

All teams share the same orchestration infrastructure (plan lifecycle, WebSocket streaming, team config management) but differ in their agent definitions, MCP tools, and data sources.

✅ *Verified in code:* `docs/architecture/project-spec.md` §5, `data/agent_teams/*.json`
