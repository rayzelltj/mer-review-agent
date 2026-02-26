# Controls (Trust Boundaries, Identity, Secrets, Observability)

This file inventories the major security-relevant boundaries and control points inferred from the repo, plus items to confirm against the live Azure environment.

## Live Validation Snapshot (2026-02-21)

Verified against deployed backend container app `ca-prodmvpwrf6y` in `RG-Automation_Engine-001`:
- Backend FQDN resolves and readiness probe responds:
  - `GET /readyz` -> `200 {"status":"ready"}`
- Auth-sensitive endpoints reject unauthenticated requests:
  - `GET /api/qbo/status` -> `401 Unauthorized`
- Backend auth env posture (non-secret values):
  - `EASYAUTH_ENABLED=true`
  - `AAD_TOKEN_VALIDATION_ENABLED=true`
  - `ALLOW_UNVERIFIED_IDENTITY_HEADERS=false`
  - `AAD_ALLOWED_AUDIENCES` includes:
    - `55483d14-3ac8-42dd-9a68-232417237515`
    - `api://55483d14-3ac8-42dd-9a68-232417237515`
    - `d013cea5-1c02-403c-95c3-60fbe22be086`
    - `api://d013cea5-1c02-403c-95c3-60fbe22be086`

Current blocker for fully automated API smoke from Azure CLI:
- `az account get-access-token --resource api://<allowed-audience>` returns `AADSTS65001` (missing tenant consent for Azure CLI app).
- Required one-time action:
  - `az login --tenant "<tenant-id>" --scope "api://<allowed-audience>/.default"`

## Trust Boundaries

1) **User Browser (Internet) -> Frontend Web App (App Service)**
- Protocol: HTTPS
- Boundary: untrusted client -> trusted service
- Controls (repo intent): optional Entra sign-in (see `docs/azure_app_service_auth_setup.md`), UI-driven feature flags via `/config` (`src/frontend/frontend_server.py`)
- TBD (live): whether App Service Authentication (“EasyAuth”) is enabled and enforced

2) **Frontend Web App -> Backend API (Container App)**
- Protocol: HTTPS (browser-originated API calls)
- Boundary: public web tier -> API tier
- Controls (repo intent): bearer token validation and/or EasyAuth header parsing (`src/backend/auth/auth_utils.py`)
- Risks to validate:
  - Backend Container App ingress is external in `infra/main.bicep` (publicly reachable unless restricted)
  - If identity is accepted via `x-ms-client-principal-id` alone, callers can spoof identity unless `ALLOW_UNVERIFIED_IDENTITY_HEADERS=true` is tightly controlled

3) **Backend API -> MCP Server (Container App)**
- Protocol: MCP over Streamable HTTP (`/mcp`)
- Boundary: service-to-service (still over network)
- Controls (repo intent):
  - Backend forwards the end-user token to MCP as `x-user-auth-token` and `Authorization` (`src/backend/v4/magentic_agents/common/lifecycle.py`)
  - MCP can optionally validate JWT via JWKS/issuer/audience when `ENABLE_AUTH=true` (`src/mcp_server/mcp_server.py`)
- TBD (live): whether MCP ingress is restricted and whether auth is enabled

4) **MCP Server -> Backend API (fan-out for finance/QBO calls)**
- Protocol: HTTPS
- Boundary: tool service calling back into API tier
- Controls (repo intent):
  - MCP finance tools require a user auth token by default (`MCP_REQUIRE_USER_AUTH=true`) and call backend endpoints with that token (`src/mcp_server/services/finance_service.py`)

5) **Backend API -> External APIs**
- **Intuit QBO** (OAuth2 + REST): `src/backend/api/qbo.py`, `src/backend/connectors/qbo/*`
- **Google Drive** (OAuth2, optional): env keys present in `src/backend/.env.example`
- Boundary: outbound to third-party services over public internet
- Controls: OAuth2 client secrets + refresh tokens must be protected; egress restrictions are only as strong as the network posture (TBD)

6) **Backend API -> Azure Managed Services**
- **Azure AI Foundry / OpenAI deployments** (Cognitive Services account + AI Project)
- **Azure AI Search**
- **Cosmos DB**
- **Storage Account (Blob)**
- **Key Vault**
- Boundary: service-to-service within Azure, often over private endpoints in WAF mode
- Controls (repo intent): Managed Identity auth (user-assigned identity), RBAC, private endpoints + private DNS (except Search, currently public in Bicep)

## Identities and Authentication

**End-user identity sources (backend)**
- Bearer token from `Authorization: Bearer ...` (validated via Entra JWKS) (`src/backend/auth/auth_utils.py`)
- EasyAuth-style headers (`x-ms-client-principal`, `x-ms-token-aad-id-token`) if the backend is fronted by an EasyAuth-enabled tier (`src/backend/auth/auth_utils.py`)
- Dev-only fallback user when enabled (`ALLOW_SAMPLE_USER_FALLBACK=true` in dev)

**Service identities (Azure)**
- User-assigned managed identity: `id-<solutionSuffix>` (attached to backend/mcp container apps and used for Key Vault references and Azure SDK auth)
- System-assigned identities:
  - AI Project (created with system identity in `infra/modules/ai-project.bicep`)
  - Search service (system identity enabled in `infra/main.bicep`)
  - Storage account (system identity enabled in `infra/main.bicep`)

**CI/CD identities**
- GitHub Actions uses an Azure service principal (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`) for deployments (`.github/workflows/deploy.yml`, `.github/workflows/deploy-release.yml`)
- Azure DevOps pipeline uses `azd` with an Azure service connection (`.azdo/pipelines/azure-dev.yml`)

## Secrets and Sensitive Data (Do Not Print)

**In Azure**
- Key Vault secret: `AzureAISearchAPIKey` (stored/managed by Bicep) (`infra/main.bicep`)
- Container Apps secrets:
  - Backend uses a Key Vault reference secret `azure-ai-search-api-key` (preferred)
  - Any inline secrets (TBD) must be identified via live discovery without printing values

**In data stores**
- Cosmos DB stores QBO refresh tokens and other state (treat as sensitive):
  - `data_type="qbo_client"` records include `refresh_token` (`src/backend/connectors/qbo/client_store.py`)

**In CI/CD**
- GitHub secrets:
  - Azure SP credentials
  - ACR credentials
  - Notification webhook URLs (Logic App) (present in workflows; values must remain secret)

**Local/dev**
- `.env` files are ignored globally (good) but may contain secrets (`.gitignore`)
- `src/backend/.qbo_tokens.json` exists as a local token cache and is **ignored by default** (see `.gitignore`); treat as sensitive and prevent accidental commits

## Logging, Monitoring, and Audit Points

**Backend application telemetry**
- OpenTelemetry configured to Azure Monitor when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set (`src/backend/app.py`)
- Request logging includes a correlation header `x-trace-id` (`src/backend/app.py`)

**Platform diagnostics (infra intent)**
- Log Analytics workspace + diagnostic settings are enabled when `enableMonitoring=true` (`infra/main.bicep`)
- Container Apps Environment logs configured to Log Analytics (`infra/main.bicep`)
- App Service diagnostics configured to Log Analytics + App Insights connection string (`infra/modules/web-sites.config.bicep`)

**WAF mode admin monitoring**
- Jumpbox VM uses monitoring agent + Data Collection Rules when enabled (`infra/main.bicep`)

## Control Gaps / Design Constraints (Repo Notes)

- **Azure AI Search is public** in `infra/main.bicep` (private endpoints commented out) due to agent connectivity issues; this increases exposure and makes RBAC/API-key controls more critical.
- Backend and MCP Container Apps use **external ingress** in `infra/main.bicep`; if auth is disabled, endpoints are internet-reachable.
- Header-only identity (`x-ms-client-principal-id`) is rejected by default unless `ALLOW_UNVERIFIED_IDENTITY_HEADERS=true`; enabling it increases spoofing risk if the backend is publicly reachable.

## TBD (Evidence Needed From Live Azure)

Provide the outputs listed in `docs/architecture/architecture.md` under “Azure Discovery Commands”, then update this document with:
- Which identities are actually attached to each app (backend/mcp/frontend)
- Where secrets are actually stored (Key Vault vs inline secrets vs CI variables)
- Which resources have public network access enabled/disabled in your live environment
- Where logs/metrics are routed (workspace/resource IDs, retention policies)
