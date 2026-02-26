# Local Development — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified from config files and scripts
> **See also:** [docs/LocalDevelopmentSetup.md](../LocalDevelopmentSetup.md), [docs/NON_DEVCONTAINER_SETUP.md](../NON_DEVCONTAINER_SETUP.md)

---

## Prerequisites

| Dependency | Required Version | Purpose |
|---|---|---|
| **Python** | 3.11+ | Backend + MCP server |
| **Node.js** | 18+ | Frontend build |
| **npm** | 9+ | Frontend package management |
| **uv** | Latest | Python dependency management (backend uses `uv`) |
| **Azure CLI** (`az`) | Latest | Azure resource access, token acquisition |
| **Docker** | Latest | Container builds (optional for local dev) |
| **Git** | Latest | Source control |

🔍 *Inferred from:* `pyproject.toml` files, `package.json`, `azure.yaml`, deployment scripts

---

## Repository Structure

```
src/
├── backend/          # FastAPI backend (Python)
│   ├── app.py        # Main entry point
│   ├── .env.example  # Environment template
│   ├── .env.qbo      # QBO-specific env template
│   └── pyproject.toml
├── frontend/         # React SPA (TypeScript)
│   ├── src/          # Source code
│   ├── .env.example  # Frontend env template
│   └── package.json
├── mcp_server/       # FastMCP tool server (Python)
│   ├── mcp_server.py # Main entry point
│   ├── .env.example  # MCP env template
│   └── pyproject.toml
└── tests/            # Cross-service tests
```

---

## Setup

### 1. Clone and Enter

```bash
git clone <repo-url>
cd Multi-Agent-Custom-Automation-Engine-Solution-Accelerator-1
```

### 2. Backend Setup

```bash
cd src/backend

# Copy and configure environment
cp .env.example .env
# Edit .env with your Azure resource values (see Environment Variables below)

# If using QBO features:
cp .env.qbo .env.qbo.local
# Edit with your Intuit app credentials

# Install dependencies
uv sync

# Run backend
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 3. MCP Server Setup

```bash
cd src/mcp_server

# Copy and configure environment
cp .env.example .env
# Edit .env — set BACKEND_URL to point to your local backend

# Install dependencies
uv sync

# Run MCP server
uv run python mcp_server.py
```

### 4. Frontend Setup

```bash
cd src/frontend

# Copy and configure environment
cp .env.example .env
# Set API_URL to point to your local backend

# Install dependencies
npm install

# Run dev server
npm start
```

---

## Environment Variables

### Backend (`src/backend/.env.example`)

| Variable | Required | Description |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Yes | Azure OpenAI / AI Foundry endpoint |
| `AZURE_OPENAI_API_KEY` | Conditional | API key (if not using MI) |
| `COSMOS_ENDPOINT` | Yes | Cosmos DB endpoint |
| `COSMOS_KEY` | Conditional | Cosmos DB key (if not using MI) |
| `AZURE_AI_SEARCH_ENDPOINT` | Yes | AI Search endpoint |
| `AZURE_AI_SEARCH_API_KEY` | Yes | AI Search API key |
| `AZURE_STORAGE_ACCOUNT_NAME` | Yes | Blob Storage account |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | App Insights telemetry |
| `MCP_SERVER_URL` | Yes | MCP server URL (e.g., `http://localhost:9000`) |
| `SUPPORTED_MODELS` | No | Comma-separated model list |
| `ORCHESTRATION_RUN_TTL_SECONDS` | No | Run expiry TTL |
| `CORS_ALLOWED_ORIGINS` | No | Frontend origin for CORS |
| `EASYAUTH_ENABLED` | No | Enable EasyAuth header parsing |
| `AAD_TOKEN_VALIDATION_ENABLED` | No | Enable JWT validation |
| `ALLOW_SAMPLE_USER_FALLBACK` | No | Allow dev-mode sample user (set to `true` for local dev) |

### QBO-Specific (`src/backend/.env.qbo`)

| Variable | Required for QBO | Description |
|---|---|---|
| `QBO_ENV` | Yes | `sandbox` or `production` |
| `QBO_CLIENT_ID` | Yes | Intuit OAuth app client ID |
| `QBO_CLIENT_SECRET` | Yes | Intuit OAuth app client secret |
| `QBO_REALM_ID` | Yes | Default QBO company realm ID |
| `QBO_REDIRECT_URI` | Yes | OAuth callback URL |
| `QBO_OAUTH_SCOPES` | Yes | OAuth scopes |

### MCP Server (`src/mcp_server/.env.example`)

| Variable | Required | Description |
|---|---|---|
| `HOST` | No | Server host (default: `0.0.0.0`) |
| `PORT` | No | Server port (default: `9000`) |
| `BACKEND_URL` | Yes | Backend URL for fan-out calls |
| `ENABLE_AUTH` | No | Enable JWT auth for MCP |
| `MCP_REQUIRE_USER_AUTH` | No | Require user auth tokens |
| `TENANT_ID` | Conditional | Azure AD tenant (if auth enabled) |
| `CLIENT_ID` | Conditional | Azure AD client ID (if auth enabled) |
| `DATASET_PATH` | No | Path to data tool datasets |

### Frontend (`src/frontend/.env.example`)

| Variable | Required | Description |
|---|---|---|
| `API_URL` | Yes | Backend API URL |
| `ENABLE_AUTH` | No | Enable frontend auth |
| `APP_ENV` | No | `development` or `production` |

✅ *Verified in code:* `src/backend/.env.example`, `src/backend/.env.qbo`, `src/mcp_server/.env.example`, `src/frontend/.env.example`

---

## Run Commands

| Service | Command | URL |
|---|---|---|
| Backend | `cd src/backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload` | `http://localhost:8000` |
| MCP Server | `cd src/mcp_server && uv run python mcp_server.py` | `http://localhost:9000` |
| Frontend | `cd src/frontend && npm start` | `http://localhost:3000` |
| Frontend (build) | `cd src/frontend && npm run build` | N/A |

---

## Test Commands

```bash
# Backend unit tests (from src/backend/)
cd src/backend
uv run pytest --tb=short -q

# Run specific test file
uv run pytest tests/rules_engine/test_bs_undeposited_funds_zero.py -v

# Run all rules engine tests
uv run pytest tests/rules_engine/ -v

# Run adapter tests
uv run pytest tests/adapters/ -v

# Frontend tests (if configured)
cd src/frontend
npm test

# Frontend lint/build check
cd src/frontend
npm run build
```

✅ *Verified in code:* `pytest.ini`, `conftest.py`

---

## Common Issues

| Issue | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError` on backend start | Missing dependencies | Run `uv sync` in `src/backend/` |
| CORS errors in browser | `CORS_ALLOWED_ORIGINS` not set | Add `http://localhost:3000` to backend `.env` |
| QBO connect fails locally | `QBO_REDIRECT_URI` doesn't match local URL | Set to `http://localhost:8000/api/qbo/callback` |
| MCP tools fail | `BACKEND_URL` in MCP `.env` not pointing to backend | Set to `http://localhost:8000` |
| Auth errors | Auth enabled but no valid token | Set `ALLOW_SAMPLE_USER_FALLBACK=true` in backend `.env` |
| WebSocket connection fails | Backend not running or wrong URL | Ensure backend is running on expected port |
| Cosmos DB connection error | Missing credentials or endpoint | Verify `COSMOS_ENDPOINT` and auth (key or MI) |
| AI Search key error | Missing API key | Set `AZURE_AI_SEARCH_API_KEY` from Key Vault |

---

## Client Configuration for Testing

To test with a QBO-connected client:

1. Register at [developer.intuit.com](https://developer.intuit.com) for sandbox credentials
2. Configure `src/backend/.env.qbo` with sandbox credentials
3. Add client to `config/clients.json`:
   ```json
   {
     "clients": {
       "test_client": {
         "realm_id": "<sandbox_realm_id>",
         "counterparties": []
       }
     }
   }
   ```
4. Start all services and navigate to QBO connect in the UI
