# CLAUDE.md — Project Instructions for Claude Code

> **Project:** Multi-Agent Custom Automation Engine (MACAE) — MER Review Agent
> **Owner:** Rayzell Tjandra
> **Last updated:** 2026-02-23

---

## 🧠 Read These First (Mandatory Context)

Before making ANY code change, read and internalize these docs in order:

1. `docs/architecture/project-spec.md` — platform-wide product & technical spec
2. `docs/architecture/mer-review-agent-spec.md` — MER-specific product intent & MVP roadmap
3. `docs/mer/README.md` — index of 18 MER-specific docs (system overview, architecture, data flow, rules engine, integrations, API reference, error handling, runbook, etc.)
4. `docs/mer/system-overview.md` — what the MER Review Agent does and does not do
5. `docs/mer/architecture.md` — components, agent roles, orchestration flow
6. `docs/mer/api-reference.md` — all REST endpoints with request/response schemas
7. `docs/mer/error-handling.md` — error codes, retry strategies, exception hierarchy
8. `docs/mer/known-gaps-and-roadmap.md` — limitations, tech debt, priority next steps
9. `docs/rules/STATUS.md` — rules implementation checklist
10. `docs/rules/balance_sheet/` — per-rule specification (22 files)
11. `docs/mer/v2-implementation-spec.md` — **V2 agent evolution**: 5-phase implementation blueprint (AccountingAgent, Evidence Ledger, Correction Memory, PrepAgent, RAG)
12. `docs/mer/architecture-decision-record.md` — 10 ADRs for v2 evolution (merged agents, constrained planning, context budgeting, escalation model)

---

## 📁 Repository Structure

```
src/frontend/          → React 18 + TypeScript + Vite + Fluent UI (port :3000)
src/backend/           → FastAPI + Python 3.11+ + uv (port :8000)
src/mcp_server/        → FastMCP tool server (port :9000)
data/agent_teams/      → JSON team configurations (6 teams)
data/datasets/         → CSV/JSON data files for non-MER teams
docs/mer/              → 18 MER-specific documentation files
docs/architecture/     → Platform-wide architecture docs
docs/rules/            → Rules engine status + 22 per-rule specs
infra/                 → Bicep IaC for Azure deployment
config/                → Client configuration (clients.json)
```

### Key Entry Points

| Component | Entry File | What It Does |
|-----------|-----------|--------------|
| Backend API | `src/backend/app.py` | FastAPI app composition, mounts all routers |
| V4 Orchestration | `src/backend/v4/api/router.py` | Team init, plan creation, WebSocket, approval |
| Orchestration Engine | `src/backend/v4/orchestration/orchestration_manager.py` | Agent lifecycle, Magentic workflow, run lock |
| Agent Definitions | `src/backend/v4/magentic_agents/` | Per-agent wrappers, system prompts, lifecycle |
| QBO Connector | `src/backend/connectors/qbo/` | OAuth, token management, API client with retry |
| Drive Connector | `src/backend/connectors/drive/` | OAuth2 refresh token, Google API client |
| Rules Engine | `src/backend/common/rules_engine/` | Decorator-registered deterministic rules |
| Adapters | `src/backend/adapters/` | Data normalization (QBO → rule inputs) |
| Review API | `src/backend/api/reviews.py` | Balance sheet run lifecycle endpoints |
| QBO API | `src/backend/api/qbo.py` + `qbo_data.py` | QBO OAuth + data fetch endpoints |
| Frontend App | `src/frontend/src/App.tsx` | React Router, page layout |
| Chat/Plan Page | `src/frontend/src/pages/PlanPage.tsx` | Main chat UI, WebSocket, message display |
| Home Page | `src/frontend/src/pages/HomePage.tsx` | Team init, task submission |
| WebSocket Service | `src/frontend/src/services/WebSocketService.tsx` | Singleton WS client, reconnection |
| API Service | `src/frontend/src/api/apiService.tsx` | HTTP client with cache + dedup |
| MCP Server | `src/mcp_server/mcp_server.py` | Tool registration |
| Finance Tools | `src/mcp_server/services/finance_service.py` | MCP tools for balance sheet workflows |

---

## 🏗️ Architecture Boundaries (DO NOT VIOLATE)

1. **`src/frontend`** = UI only. No secrets, no direct API calls to external services, no business logic.
2. **`src/backend`** = API + orchestration + connectors + rules. ALL privileged operations live here.
3. **`src/mcp_server`** = Tool server called by backend agents. Calls back to backend APIs.
4. **Secrets** → Azure Key Vault (prod) or `.env` (dev). NEVER in frontend code or committed files.
5. **Auth** → Microsoft Entra ID / EasyAuth in production. Backend validates tokens. Frontend only passes them.
6. **Team configs** → JSON files in `data/agent_teams/`. Extend the schema, don't hardcode behavior.
7. **API contracts** → Preserve existing endpoint groups: `/api/v4/*`, `/api/qbo/*`, `/api/reviews/*`, `/api/drive/*`.

---

## 🛠️ Tech Stack

### Backend
- **Python 3.11+** with **uv** package manager
- **FastAPI** (uvicorn) — async REST + WebSocket
- **azure-ai-agents 1.2.0b5** — Azure AI Foundry agent framework
- **agent-framework >=1.0.0b251105** — Magentic orchestration (plan-first multi-agent)
- **semantic-kernel 1.35.3** — SK integration
- **azure-cosmos 4.9.0** — state persistence
- **mcp 1.13.1** — Model Context Protocol client
- **OpenTelemetry** — tracing & monitoring

### Frontend
- **React 18** + **TypeScript** + **Vite**
- **Fluent UI v9** (`@fluentui/react-components`)
- **react-router-dom v7** — routing
- **react-markdown** — message rendering
- **axios** — HTTP client

### Infrastructure
- **Azure Container Apps** — backend + MCP
- **Azure App Service** — frontend (container)
- **Azure Cosmos DB** — state, tokens, run records
- **Azure Blob Storage** — artifacts, snapshots
- **Azure Key Vault** — secrets
- **Azure AI Foundry / OpenAI** — LLM
- **Azure AI Search** — grounding data

---

## 🧪 Testing

### How to Run Tests
```bash
# Backend tests (from src/backend/)
cd src/backend && uv run pytest --tb=short -q

# Frontend tests
cd src/frontend && npm test

# Frontend build check
cd src/frontend && npm run build
```

### Test Structure
- `src/backend/tests/` — backend unit tests (adapters, agents, API, auth, connectors, middleware, models, pipelines, rules_engine)
- `src/tests/` — cross-component tests (agents, mcp_server)
- `tests/e2e-test/` — end-to-end tests (Playwright)
- `conftest.py` at repo root + `src/backend/tests/conftest.py`

### Test Expectations
- Every behavior change MUST have corresponding tests
- Use `pytest-asyncio` for async tests
- Mock external services (QBO, Drive, Azure AI, Cosmos) — never call real APIs in tests
- Follow existing fixture patterns in `conftest.py`
- Test files mirror source structure: `src/backend/tests/connectors/`, `src/backend/tests/adapters/`, etc.

---

## 🚨 Known Issues (Current State — What Needs Fixing)

These are the verified issues from code audit. This is your primary work backlog:

### P0 — Critical UX Issues

#### 1. Chat Follow-ups Create Separate Windows
- **Symptom:** When user asks a follow-up after a completed run, it navigates to a new `/plan/{id}` page instead of continuing in the same thread.
- **Root cause:** `PlanPage.tsx` → `handleSendMessage()` calls `TaskService.createPlan()` which always creates a new Plan with a new `plan_id`, then `navigate(`/plan/${response.plan_id}`)`.
- **Backend note:** The `session_id` IS passed through and the orchestration manager does attempt to preserve executor state when session matches. But the frontend creates a new page/WebSocket.
- **Fix direction:** Implement conversation-centric threading. Follow-ups within the same session should append to the current plan page, not create a new one. Consider adding a `/api/v4/follow_up` endpoint or modifying `process_request` to support appending to an existing plan.
- **Files:** `src/frontend/src/pages/PlanPage.tsx`, `src/backend/v4/api/router.py`

#### 2. App Gets Stuck / Unresponsive
- **Causes:**
  - **Run lock:** Single-user lock in `orchestration_manager.py` with 30-min TTL. If a run fails without cleanup, user is blocked.
  - **Stall detection disabled:** `max_stall_count=0` in workflow config means the 20-round orchestration loop never detects stalls.
  - **`isProcessing` flag sticky:** Set to `true` on plan creation, only reset on specific terminal events. If WebSocket drops, chat input stays disabled.
  - **Team init ~20s:** `HomePage.tsx` blocks on `init_team` which can take ~20 seconds.
  - **Approval timeout:** 300s (5-min) blocking wait for user approval.
- **Files:** `src/backend/v4/orchestration/orchestration_manager.py`, `src/frontend/src/pages/PlanPage.tsx`, `src/frontend/src/pages/HomePage.tsx`

#### 3. Chat Output Contains Code-Like Text
- **Symptom:** Users see "MagenticManager", "bs_submit_evidence_request", "ReviewAgent", raw JSON, Python repr strings.
- **Causes:**
  - `response_handlers.py` sends raw `agent_name` field (internal names) in WebSocket payloads.
  - Plan prompts in `lifecycle.py` explicitly instruct LLM to include agent names in plan steps.
  - `AgentToolMessage` sends raw tool function names like `bs_submit_evidence_request`.
  - No post-processing of final answer text to strip internal names.
  - Streaming buffer in `PlanPage.tsx` renders content via ReactMarkdown with no sanitization.
- **Fix direction:** Add an output sanitization layer. Map internal agent names to user-friendly labels. Filter tool call names from visible messages. Add a `sanitize_for_display()` function in both backend (before WebSocket send) and frontend (before render).
- **Files:** `src/backend/v4/callbacks/response_handlers.py`, `src/backend/v4/magentic_agents/common/lifecycle.py`, `src/frontend/src/pages/PlanPage.tsx`

### P1 — UX Friction

#### 4. QBO Auth Flow Issues
- **Causes:**
  - Auth token can be lost during OAuth redirect flow (App → Intuit → back, token was in memory).
  - No loading/progress indicator on QBO connect/callback pages (bare text only).
  - Fragile cross-tab communication (`postMessage` + `storage` events).
  - Callback page redundantly re-resolves API URL.
- **Files:** `src/frontend/src/pages/QboConnectPage.tsx`, `src/frontend/src/pages/QboCallbackPage.tsx`

#### 5. Latency / Slow Responses
- **Causes:**
  - Agent cold start: creating Azure AI agents on every orchestration run.
  - MCP tool polling: `bs_wait_for_review` polls up to 120s default / 600s max.
  - Max 20 orchestration rounds with no stall detection.
  - ReviewAgent runs synchronous monolith pipeline (~25-45s) with no streaming progress.
- **Files:** `src/backend/v4/orchestration/orchestration_manager.py`, `src/mcp_server/services/finance_service.py`

#### 6. Limited Question Flexibility
- **Causes:**
  - Prescriptive plan prompts with fixed routing patterns in `lifecycle.py`.
  - MCP tool surface is narrow (finance-only).
  - Single team per session; no cross-team or general-purpose routing.
  - RAI content safety gating with no user guidance on rejection.
- **Files:** `src/backend/v4/magentic_agents/common/lifecycle.py`, `src/mcp_server/services/finance_service.py`

---

## 🎯 Owner's Priorities

The project owner's primary focus is **developing new MER review rules and refining/correcting current ones**. All infrastructure, UI/UX, and platform improvements should support this goal by making the review pipeline more reliable, the user experience smoother, and the development workflow faster.

### Goal State
The web app should feel like **ChatGPT or Claude AI** — smooth, conversational, human-readable — but purpose-built for month-end financial review. Users should be able to:
- Run balance sheet reviews with a single natural-language request
- Ask follow-up questions in the same conversation thread
- Get human-readable results (no internal agent/tool names)
- Connect QBO smoothly with clear progress indicators
- Ask a wide range of review-related questions beyond the current fixed patterns

---

## 📐 Code Style & Conventions

### Python (Backend)
- Type hints on all function signatures
- Async functions where I/O is involved
- Pydantic models for request/response schemas
- Decorator-registered rules (see `src/backend/common/rules_engine/`)
- Pure-function adapters (see `src/backend/adapters/`)
- Structured logging with OpenTelemetry
- No `print()` statements — use `logging` module
- PII-aware: never log tokens, credentials, or client financial data

### TypeScript (Frontend)
- Functional components with hooks
- Fluent UI v9 components (not v8)
- `axios` for HTTP, custom `WebSocketService` for WS
- react-markdown for rendering chat messages
- Services layer (`src/frontend/src/services/`) for business logic
- Pages layer (`src/frontend/src/pages/`) for route-level components
- Components layer (`src/frontend/src/components/`) for reusable UI

### Git
- Conventional commit messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`
- One logical change per commit
- Always run tests before committing

---

## 🔄 Development Workflow

### Local Development Setup
```bash
# Backend
cd src/backend
cp .env.example .env  # fill in Azure credentials
uv sync
uv run uvicorn app:app --reload --port 8000

# Frontend
cd src/frontend
npm install
npm run dev  # starts on :3000

# MCP Server
cd src/mcp_server
uv sync
uv run python mcp_server.py  # starts on :9000
```

### Environment Variables (Backend)
Key vars needed in `src/backend/.env`:
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT_NAME`
- `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE`
- `AZURE_AI_SEARCH_ENDPOINT`, `AZURE_AI_SEARCH_KEY`
- `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_REDIRECT_URI`
- `DRIVE_CLIENT_ID`, `DRIVE_CLIENT_SECRET`, `DRIVE_REFRESH_TOKEN`
- `MCP_SERVER_ENDPOINT`

### Deployment
- Infrastructure: `infra/main.bicep` via `azd up` or `az deployment`
- Backend + MCP: Azure Container Apps (Docker)
- Frontend: Azure App Service (Docker)
- Deploy script: `infra/scripts/deploy_prod.sh`

---

## ⚠️ Guardrails (NEVER Do These)

1. **Never** put secrets, tokens, or API keys in frontend code or committed files
2. **Never** bypass backend auth checks — all privileged operations go through backend
3. **Never** replace multi-agent orchestration with single-step LLM calls
4. **Never** hardcode environment-specific URLs or tenant IDs
5. **Never** move business logic (rules, adapters, connectors) to the frontend
6. **Never** break existing API contracts without updating all consumers
7. **Never** commit without running `uv run pytest` (backend) and `npm run build` (frontend)
8. **Never** log PII, financial data, or credentials
9. **Never** remove or weaken existing security controls (RBAC, token encryption, etc.)
10. **Never** make changes to rules engine behavior without updating `docs/rules/` specs

---

## 🔍 When Investigating Issues

1. **Read the relevant docs first** — `docs/mer/` has 15 docs covering every subsystem
2. **Trace the full request path** — frontend → API router → orchestration → agents → MCP tools → response → WebSocket → UI
3. **Check error handling docs** — `docs/mer/error-handling.md` catalogs all error codes and retry strategies
4. **Check the API reference** — `docs/mer/api-reference.md` has all endpoints with schemas
5. **Use the runbook** — `docs/mer/runbook.md` has decision trees for common failure modes
6. **Check known gaps** — `docs/mer/known-gaps-and-roadmap.md` before implementing features that may already be planned

---

## 🤖 Agent Team Workflow (How to Work on This Project)

When working on this codebase, operate as a team of specialists. For each task:

### Phase 1: Understand
- Read all relevant docs and source code
- Identify the full call chain affected by the change
- List all files that need modification
- **Ask counter-questions** about edge cases, unclear requirements, and assumptions

### Phase 2: Plan
- Break the change into atomic, testable steps
- Identify what tests need to be written/updated
- Identify what docs need to be updated
- Check for conflicts with existing patterns
- **Challenge the plan** — what could go wrong? What edge cases are missed?

### Phase 3: Execute
- Implement one atomic step at a time
- Write tests alongside or before code (TDD when possible)
- Run tests after each step: `cd src/backend && uv run pytest --tb=short -q`
- Run frontend build check: `cd src/frontend && npm run build`

### Phase 4: Verify
- Run full test suite
- Check for regressions in related subsystems
- Verify the change against the user's original requirement
- Review for security implications
- **Devil's advocate pass** — argue against the implementation, find weaknesses

### Phase 5: Document
- Update relevant docs in `docs/mer/` or `docs/rules/`
- Update this CLAUDE.md if architecture or patterns changed
- Write a clear commit message

---

## 📚 Quick Reference: MER Review Pipeline

```
User submits "Run balance sheet review for Client X, period 2026-01-31"
  │
  ├─ POST /api/v4/process_request → creates Plan + starts orchestration
  │
  ├─ WebSocket /api/v4/socket/{process_id} → streams updates
  │
  ├─ Orchestrator (MagenticManager) generates plan → sends plan_approval_request
  │
  ├─ User approves → POST /api/v4/plan_approval
  │
  ├─ Agent execution sequence:
  │   ├─ ReviewAgent → checks QBO connection, then calls run_balance_sheet_review
  │   │   (synchronous: fetch → normalize → rules → report in one API call)
  │   └─ ProxyAgent → relays clarification questions to user (if needed)
  │
  └─ Final result → WebSocket final_result_message → UI renders report
```

### Review Run Status Lifecycle
```
queued → running → raw → fetched → done
                                  ↘ failed
```

### Rule Result Statuses
`PASS` | `FAIL` | `WARN` | `NEEDS_REVIEW` | `NOT_APPLICABLE`

### Rule Severities
`CRITICAL` | `HIGH` | `MEDIUM` | `LOW` | `INFO`
