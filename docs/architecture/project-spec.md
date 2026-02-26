# MACAE Project Specification (Copilot Context)

## 1. Document Purpose

This document is the working product and technical specification for the **Multi-Agent Custom Automation Engine (MACAE)** repository.

Primary goal: give AI coding assistants (Copilot/Codex) stable project context so implementation suggestions stay aligned with this codebase.

MER-specific product guardrails:
- `docs/architecture/mer-review-agent-spec.md`

## 2. Product Summary

MACAE is an Azure-hosted, multi-agent automation platform where a user:

- selects a team of specialized agents,
- submits a task,
- receives a generated plan,
- optionally provides human approval or clarifications,
- runs coordinated agent execution with streamed status and final output.

The project is a solution accelerator, intended to be adapted for enterprise workflows such as HR onboarding, marketing content planning, retail remediation, RFP analysis, contract compliance review, and balance sheet review.

## 3. Problem Statement

Organizations struggle to coordinate complex workflows across teams and systems. Manual orchestration is slow, inconsistent, and error-prone.

MACAE addresses this by combining:

- orchestration logic,
- specialized agent teams,
- optional human-in-the-loop controls,
- enterprise data/integration connectors.

## 4. Scope

### In Scope

- Multi-team agent orchestration with plan-first workflow.
- Real-time run status via WebSocket.
- Team configuration management (built-in and uploaded JSON teams).
- Integration with Azure AI Foundry/OpenAI, Azure AI Search, Cosmos DB, Blob Storage, Key Vault.
- Optional enterprise connectors (QuickBooks Online, Google Drive).
- Balance sheet review pipeline with rules engine and artifact/snapshot retrieval.

### Out of Scope

- Single-agent chat bot behavior without orchestration.
- Mobile-native client apps.
- Hardcoded, one-off workflow logic in frontend components.
- Storing secrets in source code or client-side runtime.

## 5. Primary Use Cases and Teams

Team definitions live under `data/agent_teams/*.json`.

Current first-party teams include:

- `Retail Customer Success Team` (`data/agent_teams/retail.json`)
- `Human Resources Team` (`data/agent_teams/hr.json`)
- `Product Marketing Team` (`data/agent_teams/marketing.json`)
- `RFP Team` (`data/agent_teams/rfp_analysis_team.json`)
- `Contract Compliance Review Team` (`data/agent_teams/contract_compliance_team.json`)
- `Balance Sheet Review Team` (`data/agent_teams/balance_sheet_review_team.json`)

## 6. System Architecture

### Core Runtime Services

- Frontend web app: React + TypeScript (`src/frontend/src/*`) served by FastAPI static server (`src/frontend/frontend_server.py`).
- Backend API and orchestrator: FastAPI (`src/backend/app.py`, `src/backend/v4/*`).
- MCP tool server: FastMCP (`src/mcp_server/mcp_server.py`, `src/mcp_server/services/*`).

### Main Data/Infra Dependencies

- Azure AI Foundry / Azure OpenAI
- Azure AI Search
- Azure Cosmos DB
- Azure Blob Storage
- Azure Key Vault
- Azure Monitor (Log Analytics + App Insights)

### Deployment Shape

Infrastructure is defined in Bicep under `infra/` (entry: `infra/main.bicep`) and deploys:

- Frontend on App Service (container),
- Backend and MCP on Azure Container Apps,
- supporting AI/data/security/observability resources.

## 7. Key Runtime Flows

### Flow A: Team Initialization

1. Frontend calls `GET /api/v4/init_team`.
2. Backend resolves authenticated user.
3. Backend ensures at least one usable team exists for the user (including default provisioning path).
4. Backend sets current team and prepares orchestration context.

Relevant code:

- `src/frontend/src/services/TeamService.tsx`
- `src/backend/v4/api/router.py`

### Flow B: Plan Creation and Execution

1. User submits task from UI.
2. Frontend calls `POST /api/v4/process_request`.
3. Backend creates/updates plan state and streams updates.
4. Frontend listens on `GET /api/v4/socket/{process_id}` websocket.
5. User approves with `POST /api/v4/plan_approval` when required.
6. Orchestrator runs multi-agent execution and returns final status.

Relevant code:

- `src/frontend/src/api/apiService.tsx`
- `src/backend/v4/api/router.py`
- `src/backend/v4/orchestration/orchestration_manager.py`

### Flow C: MCP Tool Invocation

1. Backend invokes MCP server tools over streamable HTTP.
2. Backend forwards user auth token for user-context operations.
3. MCP services execute domain tool logic.
4. Finance MCP tools can call backend APIs for QBO/review operations.

Relevant code:

- `src/backend/v4/magentic_agents/common/lifecycle.py`
- `src/mcp_server/mcp_server.py`
- `src/mcp_server/services/finance_service.py`

### Flow D: QBO + Balance Sheet Review

1. User connects QuickBooks via `/api/qbo/*` OAuth flow.
2. Backend stores tokens/state (Cosmos preferred, dev fallback possible).
3. Review runs start via `/api/reviews/balance-sheet/*`.
4. Rules engine evaluates findings and generates summary/artifacts.
5. Snapshots and artifacts are retrievable via review endpoints.

Relevant code:

- `src/backend/api/qbo.py`
- `src/backend/api/reviews.py`
- `src/backend/common/rules_engine/*`

## 8. API Surface (High-Level)

Major endpoint groups:

- `/api/v4/*` for orchestration, plans, team management, websocket run updates.
- `/api/qbo/*` and `/qbo/*` for QuickBooks OAuth/connectivity.
- `/api/reviews/*` for balance sheet runs, rules, snapshots, artifacts.
- `/api/drive/*` for optional Drive evidence operations.

Backend app composition is in `src/backend/app.py`.

## 9. Data and State Model (Conceptual)

- User identity: resolved from bearer token / EasyAuth-compatible headers.
- Team configuration: JSON definitions, persisted and selected per user.
- Plan/session state: stored and streamed through backend orchestration services.
- Review run state: `run_id`, `client_id`, `period_end`, status lifecycle, findings, artifacts.
- Connector credentials/tokens: stored server-side (Cosmos or secure config paths), never client-side.

## 10. Security and Compliance Expectations

- Do not place secrets/tokens in frontend code or checked-in files.
- Prefer Managed Identity + Key Vault references for service-to-service access.
- Treat QBO and Drive tokens as sensitive.
- Keep authentication checks in backend for all privileged operations.
- Preserve or improve telemetry and traceability (`x-trace-id`, OpenTelemetry hooks).

Reference docs:

- `docs/architecture/controls.md`
- `docs/TRANSPARENCY_FAQ.md`

## 11. Non-Functional Requirements

- Observability: maintain structured logs, traces, health endpoints.
- Reliability: avoid duplicate run creation where idempotent behavior exists.
- Extensibility: new teams/services should fit existing config-driven model.
- Maintainability: keep domain logic in backend/adapters/services, not UI.

## 12. Repository Map for Contributors

- Product/architecture docs: `docs/`, especially `docs/architecture/*`
- Infrastructure: `infra/*`
- Backend runtime: `src/backend/*`
- MCP runtime: `src/mcp_server/*`
- Frontend runtime: `src/frontend/*`
- Team configs/datasets: `data/*`
- Automated tests: `src/backend/tests/*`, `src/tests/*`

## 13. Copilot Guardrails (Important)

When generating code for this repo, Copilot should:

- Keep frontend-backend contracts consistent with existing endpoint paths.
- Prefer extending service layers (`apiService`, backend routers/services) over embedding logic directly in UI components.
- Reuse existing team-config schema and orchestration patterns.
- Preserve websocket-based progress flow and plan approval flow.
- Add tests near existing test structure for changed behavior.

Copilot should not:

- Introduce new auth patterns that bypass existing backend identity checks.
- Hardcode secrets, tenant IDs, or environment-specific endpoints.
- Replace existing orchestration with single-step LLM calls for multi-step workflows.
- Move sensitive business logic to client-side code.

## 14. Current Constraints and Known Tradeoffs

- Azure AI Search networking/private endpoint posture can vary by environment; do not assume strict private-only connectivity without checking deployment config.
- Some auth behavior is environment-driven (EasyAuth on/off, local dev fallbacks); changes must preserve secure production defaults.
- Balance sheet review logic is actively evolving; preserve run-state compatibility when changing review pipeline contracts.

## 15. One-Paragraph Copilot Context (Quick Paste)

MACAE is an Azure-hosted multi-agent orchestration platform with a React frontend (`src/frontend`), FastAPI backend orchestrator (`src/backend`), and FastMCP tool server (`src/mcp_server`). Users select agent teams from JSON configs (`data/agent_teams`), submit tasks, receive generated plans, optionally approve/clarify, and execute runs with websocket status updates (`/api/v4/socket/{process_id}`). Backend integrates with Azure AI Foundry/OpenAI, Azure AI Search, Cosmos DB, Blob Storage, and Key Vault, plus optional QBO/Drive connectors (`/api/qbo`, `/api/reviews`, `/api/drive`). Keep changes contract-compatible, security-first, and aligned with existing service boundaries.
