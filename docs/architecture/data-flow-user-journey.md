# Data Flow — User Journey (Step-by-Step)

How a review request flows through the system, from opening the app to viewing results.

---

## Step 1 — Open the Web App

The user navigates to the website in their browser.

| Service | Detail |
|---------|--------|
| **Azure App Service** (`app-<suffix>`) | Serves the React frontend as a static site on port 3000 |

---

## Step 2 — Sign In

A Microsoft login page appears. The user enters their work email and password.

| Service | Detail |
|---------|--------|
| **Microsoft Entra ID** | Verifies the user's identity and returns a secure token |
| **Azure App Service (EasyAuth)** | Manages the auth session — the token lives in the browser session, not in our database |

---

## Step 3 — App Home Screen Loads

The app sets up the user's workspace and loads their agent team configuration.

| Service | Detail |
|---------|--------|
| **FastAPI Backend** (Container App, port 8000) | Handles the `/api/v4/teams` request |
| **Cosmos DB** — `macae` / `memory` | Team config is loaded: team name, agent list, starting tasks, AI model settings (one record per user per team) |

---

## Step 4 — Connect QuickBooks (if needed)

Only required for finance reviews. If QuickBooks isn't connected yet, the user authorizes access.

| Service | Detail |
|---------|--------|
| **Intuit OAuth** (external) | User clicks "Connect QBO" → popup opens to Intuit's login → user authorizes access to their accounting data |
| **FastAPI Backend** — `/api/qbo/callback` | Receives the OAuth callback with authorization code |
| **Cosmos DB** — `macae` / `memory` | Stores: refresh token, realm ID, client ID, expiry timestamp. Access tokens are **not** stored — they are fetched on-demand each time |

> If already connected, this step is skipped.

---

## Step 5 — Submit a Request

The user types a request in the chat, e.g.:
> *"Run a balance sheet review for Client ABC, period ending Jan 2026"*

| Service | Detail |
|---------|--------|
| **React Frontend** | Sends the message over a **WebSocket** connection to the backend |
| **FastAPI Backend** — WebSocket handler | Receives the message and routes it to the orchestration layer |

---

## Step 6 — AI Creates a Plan

The backend sends the request to Azure AI Foundry, which creates a step-by-step execution plan.

| Service | Detail |
|---------|--------|
| **Azure AI Foundry Project** (`proj-<suffix>`) | Hosts the AI agent that interprets the request |
| **Azure AI Services** (`aif-<suffix>`) — GPT-4.1 | Generates the plan: which agents to run, what data to pull, what rules to check |
| **Cosmos DB** — `macae` / `memory` | Plan is saved: plan ID, session ID, plan steps, status, team ID |
| **WebSocket** | Plan is streamed live to the user's screen |

---

## Step 7 — User Approves the Plan

The plan appears on screen. The user reviews it and decides to approve or reject.

| Service | Detail |
|---------|--------|
| **React Frontend** | Displays the plan with an Approve / Reject UI |
| **FastAPI Backend** | On approval → kicks off agent execution. On reject → returns to Step 5 |

---

## Step 8 — Agents Execute

A team of 5 AI agents runs in sequence. Live progress streams to the screen via WebSocket.

### Agent 1 — Connector

Connects to QuickBooks and pulls raw financial data.

| Service | Detail |
|---------|--------|
| **MCP Server** (Container App, port 9000) | Executes the QBO tool calls via FastMCP |
| **Intuit QuickBooks API** (external) | Pulls: balance sheet, account list, aging reports, transactions |
| **Cosmos DB** — `macae` / `memory` | Creates a review run record: run ID, client ID, period end date, status, snapshot keys |
| **Azure Blob Storage** — `snapshots` container | Saves raw QBO data at `snapshots/{run_id}/`: `balance_sheet.json`, `aging_ar.json`, `aging_ap.json`, `trial_balance.json`, `accounts.json`, plus transaction files |

### Agent 2 — Normalizer

Cleans and organizes the raw data into a standard format the rules engine can read.

| Service | Detail |
|---------|--------|
| **Azure AI Services** — GPT-4.1 | Processes and normalizes the data |
| **Azure Blob Storage** — `snapshots` container | Saves normalized data at `runs/{run_id}/review_inputs.json`: standardized balance sheet, prior periods, evidence bundle, reconciliation data |

### Agent 3 — Rules Checker

Runs 26 review rules against the normalized data. Each account gets: Pass, Fail, Warning, or Needs Review.

| Service | Detail |
|---------|--------|
| **Azure AI Services** — o4-mini (reasoning model) | Evaluates rules that require judgment |
| **Azure Blob Storage** — `snapshots` container | Saves results at `runs/{run_id}/findings.json` + `runs/{run_id}/bs_view.json`: per-rule results, per-account status, severity, evidence references |
| **Cosmos DB** — `macae` / `memory` | Updates the run record with: findings count, pass/fail totals, critical rule IDs, human-in-the-loop requests |

### Agent 4 — Report Builder

Creates an executive summary with a balance sheet view, key findings, and recommended next actions.

| Service | Detail |
|---------|--------|
| **Azure AI Services** — GPT-4.1 | Generates the human-readable summary |
| **Azure Blob Storage** — `snapshots` container | Saves report at `runs/{run_id}/summary.md` |
| **Cosmos DB** — `macae` / `memory` | Summary also saved inline on the run record |

### Agent 5 — Evidence Checker

Identifies missing documents (bank statements, receipts) and lists what's still needed.

| Service | Detail |
|---------|--------|
| **Azure AI Services** — GPT-4.1-mini | Checks for gaps in supporting evidence |

---

## Step 9 — Results Appear on Screen

The user sees the completed review:

- Balance sheet (current + 3 prior months)
- Per-account status (Pass / Fail / Warning)
- Key findings & flagged issues
- Missing evidence list
- Recommended next actions

| Service | Detail |
|---------|--------|
| **React Frontend** | Renders the results from data streamed via WebSocket |

---

## Step 10 — Follow-Up Questions

The user can ask follow-up questions, e.g.:
> *"Why did cash fail?"* or *"Show me the details for accounts receivable."*

| Service | Detail |
|---------|--------|
| **Azure AI Foundry Project** | AI answers using the saved results from Cosmos DB + Blob Storage |
| **Cosmos DB** — `macae` / `memory` | Each message is saved: content, sender (human or agent), plan ID, timestamp |

The user can continue asking questions or close the session.

---

## Step 11 — Review Complete

Everything is saved and persisted. The user can return anytime to view past reviews.

### Where the data lives

| Store | What's saved |
|-------|-------------|
| **Cosmos DB** — `macae` / `memory` | Plans, run records, findings summary, chat messages, QBO credentials, team config |
| **Azure Blob Storage** — `snapshots` container | Raw QBO data, normalized inputs, full findings, balance sheet view, report |

---

## Service Reference

| Service | Resource Name | Type | Role |
|---------|--------------|------|------|
| Frontend | `app-<suffix>` | Azure App Service (Linux) | Hosts React UI |
| Backend | `ca-backend-<suffix>` | Azure Container App | FastAPI orchestration API |
| MCP Server | `ca-mcp-<suffix>` | Azure Container App | Tool execution server (QBO, Drive, etc.) |
| AI Services | `aif-<suffix>` | Azure AI Services | Hosts GPT-4.1-mini, GPT-4.1, o4-mini models |
| AI Foundry Project | `proj-<suffix>` | Azure AI Foundry Project | Agent execution, AI Search connection |
| Cosmos DB | `cosmos-<suffix>` | Azure Cosmos DB (NoSQL) | Database: `macae`, Container: `memory` |
| Blob Storage | `st<suffix>` | Azure Storage Account | Container: `snapshots` |
| Identity | `id-<suffix>` | User-Assigned Managed Identity | Shared across backend, MCP, AI Services |
| Auth | — | Microsoft Entra ID + EasyAuth | User authentication |
