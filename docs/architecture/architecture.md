# MACAE Architecture (Repo-Derived)

This document is a repo-derived architecture and data-flow view of the **Multi-Agent Custom Automation Engine (MACAE)** solution accelerator. It is intentionally evidence-based (files/paths referenced below) and will be reconciled with **live Azure discovery outputs** once provided.

Diagrams:
- `docs/architecture/diagrams/architecture-c4.mmd`
- `docs/architecture/diagrams/deployment-azure.mmd`
- `docs/architecture/diagrams/data-flow-dfd.mmd`
- `docs/architecture/diagrams/auth-sequence.mmd`

Companion spec for contributors and AI assistants:
- `docs/architecture/project-spec.md`
- `docs/architecture/mer-review-agent-spec.md`
- `docs/architecture/mer-mvp1-smoke-checklist.md`

## Evidence Used (Primary Repo Sources)

Runtime/service entrypoints:
- Frontend server: `src/frontend/frontend_server.py`
- Backend API server: `src/backend/app.py`
- MCP server: `src/mcp_server/mcp_server.py`

Deployment/IaC:
- Azure resources: `infra/main.bicep`, `infra/main.parameters.json`, `infra/main.waf.parameters.json`
- Shared modules: `infra/modules/*.bicep`
- azd config (custom): `azure_custom.yaml`

CI/CD and release:
- Build/push images: `.github/workflows/docker-build-and-push.yml`
- CI “validate deploy”: `.github/workflows/deploy.yml`
- Release/stage/promote/rollback: `.github/workflows/deploy-release.yml`, `infra/scripts/deploy_prod.sh`
- Azure DevOps pipeline (optional): `.azdo/pipelines/azure-dev.yml`

Auth and integrations:
- Backend auth parsing/validation: `src/backend/auth/auth_utils.py`
- QBO OAuth + API: `src/backend/api/qbo.py`, `src/backend/connectors/qbo/*`
- MCP finance tools (QBO workflows): `src/mcp_server/services/finance_service.py`

## Repo Components (Where Things Live)

**Frontend**
- UI code: `src/frontend/src/*` (React + Fluent UI + React Router)
- Runtime server for static build + `/config`: `src/frontend/frontend_server.py`
- Container build: `src/frontend/Dockerfile`

**Backend**
- FastAPI app + middleware + routers: `src/backend/app.py`, `src/backend/api/*`
- v4 orchestration (agent_framework): `src/backend/v4/*`
- Data adapters + pipelines + rules engine (incl. QBO evidence/rules): `src/backend/adapters/*`, `src/backend/pipelines/*`, `src/backend/common/rules_engine/*`
- Container build: `src/backend/Dockerfile`

**MCP Server (Tooling)**
- FastMCP server entrypoint: `src/mcp_server/mcp_server.py`
- Tool domains/services: `src/mcp_server/services/*` (HR, marketing, finance, etc.)
- Container build: `src/mcp_server/Dockerfile`, local compose: `src/mcp_server/docker-compose.yml`

**Infrastructure + Ops**
- Bicep templates and AVM modules: `infra/`
- Post-deploy scripts (team configs + dataset indexing): `infra/scripts/selecting_team_config_and_data.sh`, `infra/scripts/upload_team_config.py`, `infra/scripts/index_datasets.py`
- Docs: `docs/` (deployment guides, auth setup, MCP docs, etc.)

## Runtime Services (Logical View)

| Service | Code | Primary Responsibilities | Default Port/Paths | Azure Host (per `infra/main.bicep`) |
|---|---|---|---|---|
| Frontend Web App | `src/frontend/*` | Serve React UI + expose runtime config (`/config`) | `:3000`, `/`, `/config`, `/health` | App Service (Linux container) |
| Backend API + Orchestrator | `src/backend/*` | Orchestration, agent lifecycle, memory store, websocket updates, QBO/Drive APIs, review pipelines | `:8000`, `/api/v4/*`, `/api/*`, `/healthz`, `/readyz` | Azure Container Apps |
| MCP Tool Server | `src/mcp_server/*` | Expose tools over MCP (`/mcp`) for agents; finance tools call backend fan-out endpoints | `:9000`, `/mcp`, `/health` | Azure Container Apps |

## Azure Deployment Topology (From `infra/main.bicep`)

MACAE’s “default” deployment (as used by CI in `.github/workflows/deploy.yml`) provisions a single resource group with:

Compute:
- **Azure Container Apps Environment**: `cae-<solutionSuffix>` (publicNetworkAccess enabled; VNet-subnet set when `enablePrivateNetworking=true`)
- **Backend Container App**: `ca-<solutionSuffix>` ingress external on `:8000`
- **MCP Container App**: `ca-mcp-<solutionSuffix>` ingress external on `:9000`
- **Frontend App Service Plan**: `asp-<solutionSuffix>` (Linux)
- **Frontend Web App for Containers**: `app-<solutionSuffix>` runs container on `:3000` and points at backend FQDN via `BACKEND_API_URL`

AI + Data:
- **Azure AI Foundry / AI Services account**: `aif-<solutionSuffix>` (kind: `AIServices`) with OpenAI model deployments (e.g., `gpt-4.1`, `gpt-4.1-mini`, `o4-mini`)
- **AI Foundry Project**: `proj-<solutionSuffix>` (system-assigned identity)
- **Azure AI Search**: `srch-<solutionSuffix>`
  - Note: in Bicep, `publicNetworkAccess` is forced **Enabled** and private endpoints are currently disabled/commented (repo note: agent connectivity issues).
- **Cosmos DB (SQL API)**: `cosmos-<solutionSuffix>` DB: `macae`, container: `memory` (partition key path `/session_id`)
- **Storage Account (Blob)**: `st<solutionSuffix>` with multiple dataset containers
- **Key Vault**: `kv-<solutionSuffix>` stores secret `AzureAISearchAPIKey` (used as Key Vault reference for backend secret `azure-ai-search-api-key`)

Identity + Observability:
- **User-assigned Managed Identity**: `id-<solutionSuffix>` attached to backend/mcp container apps and used for Azure access
- **Log Analytics Workspace**: `log-<solutionSuffix>` (or reuse via `existingLogAnalyticsWorkspaceId`)
- **Application Insights**: `appi-<solutionSuffix>` (used by backend via OpenTelemetry exporter when enabled)

Private networking (WAF-aligned, optional but enabled in `infra/main.parameters.json`):
- VNet + subnets + NSGs (`infra/modules/virtualNetwork.bicep`)
- Private DNS zones for OpenAI/AI services, Cosmos, Blob, Search, Key Vault
- Private endpoints for Cosmos, Blob, Key Vault, AI services (Search private endpoint is currently disabled in Bicep)
- Bastion + Jumpbox VM + monitoring agent/DCR for WAF-aligned administration

Terminology note: this repo uses “WAF” to mean **Well-Architected Framework alignment**, not “Web Application Firewall”.

## Key Application Flows

### 1) Orchestration (Plan + Execute + HITL)

Primary endpoints:
- Websocket updates: `GET /api/v4/socket/{process_id}` in `src/backend/v4/api/router.py`
- Start a run: `POST /api/v4/process_request` in `src/backend/v4/api/router.py`
- Human approval: `POST /api/v4/plan_approval` in `src/backend/v4/api/router.py`

High-level flow:
1. User uses the frontend UI; the UI uses backend APIs and opens a websocket for streaming status.
2. Backend creates a plan and uses `agent_framework` orchestration with optional human approval gating (`src/backend/v4/orchestration/human_approval_manager.py`).
3. Agents can use:
   - Azure AI Search “raw tool” via AI Foundry agents (preferred when a project connection exists), or
   - MCP tool server via `MCPStreamableHTTPTool` (legacy/compat path).

### 2) MCP Tool Invocation (Backend -> MCP -> Backend Fan-Out)

Key behavior:
- Backend forwards the user token to MCP calls via headers `x-user-auth-token` and `Authorization: Bearer ...` (`src/backend/v4/magentic_agents/common/lifecycle.py`).
- MCP finance tools call back into the backend (e.g., `/api/qbo/*`, `/api/reviews/*`) using the forwarded user token (`src/mcp_server/services/finance_service.py`).

This preserves “act as user” semantics for operations like QBO access, while keeping tool logic in the MCP server.

### 3) QBO OAuth (Intuit QuickBooks Online)

Key endpoints:
- API prepare/start:
  - `GET /api/qbo/connect/prepare?client_id=...` (returns authorization URL)
  - `GET /api/qbo/connect/start?client_id=...` (redirects to Intuit authorize)
- API callback:
  - `GET /api/qbo/callback?code=...&realmId=...&state=...` (exchanges code for tokens)
- Frontend pages:
  - `/qbo/connect` (initiates backend prepare call)
  - `/qbo/callback` (forwards OAuth query to `/api/qbo/callback`)

Storage behavior (repo default):
- OAuth `state` is stored in Cosmos when `QBO_CLIENT_STORE=cosmos` and in-memory only in file/dev mode.
- In Cosmos mode, OAuth state store failures return `503` (no silent fallback).
- Refresh tokens are stored in Cosmos in records like `qbo_client::<user_principal_id>::<client_id>` (`src/backend/connectors/qbo/client_store.py`).

Operational smoke guide:
- `docs/architecture/mer-mvp1-smoke-checklist.md`
- `scripts/smoke/mer_mvp1_api_smoke.sh`

Config keys (redacted):
- `QBO_CLIENT_ID=<...>`
- `QBO_CLIENT_SECRET=SECRET_REDACTED`
- `QBO_REDIRECT_URI=<...>`

### 4) Post-Deploy Data Seeding (Team Configs + Search Indexing)

Scripts:
- `infra/scripts/selecting_team_config_and_data.sh`
- `infra/scripts/upload_team_config.py` (uploads JSON team definitions to backend)
- `infra/scripts/index_datasets.py` (indexes Blob container files into Azure AI Search indices)

Used by:
- GitHub Actions deploy flow: `.github/workflows/deploy.yml`

## CI/CD + Release

Image build/push:
- `.github/workflows/docker-build-and-push.yml` builds three images and tags them per branch:
  - `macaebackend:<tag>`
  - `macaefrontend:<tag>`
  - `macaemcp:<tag>`

Validation deploy (ephemeral RG):
- `.github/workflows/deploy.yml` creates a new RG, deploys `infra/main.bicep`, runs post-deploy scripts, runs e2e, then deletes the RG.

Production release controls:
- `.github/workflows/deploy-release.yml` wraps `infra/scripts/deploy_prod.sh` for:
  - staging deploy, promote, rollback, and health checks (production-touching operations are guarded by `confirm=yes` or `--confirm`).

## Unknowns / TBD (Need Live Azure Confirmation)

Partial live confirmation captured on 2026-02-21 (see `docs/architecture/controls.md`):
- backend `ca-prodmvpwrf6y` readiness endpoint responds
- backend auth is enforced (`401` on protected route without valid token)
- token acquisition for allowed API audiences is currently blocked for Azure CLI by tenant consent (`AADSTS65001`)

Marking these as **TBD** until live discovery outputs are provided:
- Exact resource names for your deployed environment (RG name, suffixes, app names).
- Whether frontend and/or backend auth is enabled (EasyAuth vs SPA/MSAL vs no-auth).
- Whether backend/mcp container apps are publicly reachable and how inbound access is restricted (IP restrictions, auth, private ingress).
- Whether Container Apps secrets are purely Key Vault references (preferred) vs inline secrets.
- Actual diagnostic settings and where logs/metrics are routed in your subscription (workspace IDs, retention).
- Networking posture in the live environment:
  - `enablePrivateNetworking` true/false
  - Which private endpoints/DNS zones actually exist
  - Whether search is still public (expected per repo) or has been hardened in your env

## Azure Discovery Commands (Run + Paste Output)

Goal: confirm live topology **without leaking secrets**. These commands intentionally query:
- resource inventory
- endpoints/ingress
- identity wiring
- public vs private networking
- auth configuration
- diagnostics routing

Set once:
```bash
RG="<your-resource-group>"
```

### Inventory (names + types)
```bash
az group show -n "$RG" --query "{name:name,location:location,tags:tags}" -o json
az resource list -g "$RG" --query "[].{type:type,name:name,location:location}" -o table
```

### Container Apps (backend + mcp) and environment (no secret values)
```bash
az containerapp list -g "$RG" --query "[].{name:name,fqdn:properties.configuration.ingress.fqdn,targetPort:properties.configuration.ingress.targetPort,external:properties.configuration.ingress.external,envId:properties.managedEnvironmentId}" -o table

# Replace <app> with each container app name (backend + mcp)
az containerapp show -g "$RG" -n "<app>" --query "{name:name,identity:identity,ingress:properties.configuration.ingress,registries:properties.configuration.registries,secrets:properties.configuration.secrets[].{name:name,keyVaultUrl:keyVaultUrl,identity:identity},envNames:properties.template.containers[].env[].name,secretRefs:properties.template.containers[].env[?secretRef!=null].{name:name,secretRef:secretRef}}" -o json

# Container Apps Environment name can be derived from envId above (or list envs)
az containerapp env list -g "$RG" --query "[].{name:name,location:location,publicNetworkAccess:properties.publicNetworkAccess}" -o table
az containerapp env show -g "$RG" -n "<env>" --query "{name:name,publicNetworkAccess:properties.publicNetworkAccess,internal:properties.vnetConfiguration.internal,subnetId:properties.vnetConfiguration.infrastructureSubnetId,logsDestination:properties.appLogsConfiguration.destination,logAnalyticsCustomerId:properties.appLogsConfiguration.logAnalyticsConfiguration.customerId}" -o json
```

### App Service (frontend) and auth (no appsetting values)
```bash
az webapp list -g "$RG" --query "[].{name:name,defaultHostName:defaultHostName,kind:kind,httpsOnly:httpsOnly}" -o table
az webapp config container show -g "$RG" -n "<frontend_app>" -o json
az webapp config appsettings list -g "$RG" -n "<frontend_app>" --query "[].name" -o json
az webapp auth show -g "$RG" -n "<frontend_app>" -o json
```

### Core data services (network posture only)
```bash
az cosmosdb list -g "$RG" --query "[].{name:name,publicNetworkAccess:publicNetworkAccess,kind:kind}" -o table
az cosmosdb show -g "$RG" -n "<cosmos>" --query "{name:name,documentEndpoint:documentEndpoint,publicNetworkAccess:publicNetworkAccess,enableAutomaticFailover:enableAutomaticFailover,locations:locations[].locationName}" -o json

az storage account list -g "$RG" --query "[].{name:name,kind:kind,publicNetworkAccess:publicNetworkAccess,allowBlobPublicAccess:allowBlobPublicAccess}" -o table
az storage account show -g "$RG" -n "<storage>" --query "{name:name,publicNetworkAccess:publicNetworkAccess,networkRuleSet:networkRuleSet,primaryEndpoints:primaryEndpoints}" -o json

az search service list -g "$RG" --query "[].{name:name,sku:sku.name,publicNetworkAccess:publicNetworkAccess,disableLocalAuth:disableLocalAuth}" -o table
az search service show -g "$RG" -n "<search>" --query "{name:name,publicNetworkAccess:publicNetworkAccess,authOptions:authOptions,privateEndpointConnections:length(privateEndpointConnections)}" -o json

az keyvault list -g "$RG" --query "[].{name:name,publicNetworkAccess:properties.publicNetworkAccess,enableRbacAuthorization:properties.enableRbacAuthorization}" -o table
az keyvault show -g "$RG" -n "<kv>" --query "{name:name,publicNetworkAccess:properties.publicNetworkAccess,enableRbacAuthorization:properties.enableRbacAuthorization,privateEndpointConnections:length(properties.privateEndpointConnections)}" -o json
```

### Identity and registry wiring
```bash
az identity list -g "$RG" --query "[].{name:name,clientId:clientId,principalId:principalId}" -o table
az acr list -g "$RG" --query "[].{name:name,loginServer:loginServer,sku:sku.name,adminUserEnabled:adminUserEnabled}" -o table
```

### Networking (only if private networking is expected/enabled)
```bash
az network vnet list -g "$RG" --query "[].{name:name,addressPrefixes:addressSpace.addressPrefixes}" -o json
az network private-endpoint list -g "$RG" --query "[].{name:name,subnet:subnet.id,privateLinkServiceIds:privateLinkServiceConnections[].privateLinkServiceId}" -o json
az network private-dns zone list -g "$RG" --query "[].name" -o json
```

When you paste or save outputs, avoid any commands that print secret values (e.g., listing Key Vault secrets, ACR creds, search admin keys, containerapp secret values).
