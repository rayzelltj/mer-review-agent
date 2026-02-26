# Deployment & Operations — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified from infra configs and scripts
> **See also:** [docs/DeploymentGuide.md](../DeploymentGuide.md), [docs/ManualAzureDeployment.md](../ManualAzureDeployment.md)

---

## Deployment Model

The system deploys to Azure using Bicep IaC (`infra/main.bicep`) via Azure Developer CLI (`azd`) or manual deployment scripts.

### Service Topology

| Service | Azure Resource | Image Source | Port |
|---|---|---|---|
| **Frontend** | App Service (Web App) | ACR container image | `:3000` |
| **Backend** | Container App | ACR container image | `:8000` |
| **MCP Server** | Container App | ACR container image | `:9000` |

All Container Apps run in a shared Container Apps Environment. The Frontend runs on App Service with EasyAuth configured.

✅ *Verified in code:* `azure_custom.yaml`, `infra/main.bicep`

---

## Infrastructure as Code

### Entry Points

| File | Purpose |
|---|---|
| `infra/main.bicep` | Primary Bicep template |
| `infra/main_custom.bicep` | Custom deployment variant |
| `infra/main.parameters.json` | Default parameters |
| `infra/main.waf.parameters.json` | WAF-enabled parameters |
| `infra/modules/` | Reusable Bicep modules |

### Azure Resources Deployed

| Resource | Type | Purpose |
|---|---|---|
| Container Apps Environment | `Microsoft.App/managedEnvironments` | Shared runtime for Backend + MCP |
| Backend Container App | `Microsoft.App/containerApps` | API, orchestration, rules engine |
| MCP Container App | `Microsoft.App/containerApps` | Tool server |
| Frontend Web App | `Microsoft.Web/sites` | React SPA serving |
| AI Foundry / OpenAI | `Microsoft.CognitiveServices/*` | Agent reasoning (GPT-4.1) |
| AI Search | `Microsoft.Search/searchServices` | RAG indexes |
| Cosmos DB | `Microsoft.DocumentDB/databaseAccounts` | Plans, sessions, tokens, reviews |
| Blob Storage | `Microsoft.Storage/storageAccounts` | Team configs, snapshots, artifacts |
| Key Vault | `Microsoft.KeyVault/vaults` | Secrets |
| ACR | `Microsoft.ContainerRegistry/registries` | Container images |
| Log Analytics | `Microsoft.OperationalInsights/workspaces` | Logs |
| App Insights | `Microsoft.Insights/components` | Application telemetry |
| Managed Identity | `Microsoft.ManagedIdentity/userAssignedIdentities` | Cross-service auth |

Optional (configurable):
- VNet + Private Endpoints
- Bastion + Jumpbox
- WAF / Front Door

✅ *Verified in code:* `docs/architecture/architecture.md` (Azure topology), `docs/architecture/diagrams/deployment-azure.mmd`

---

## Deployment Methods

### Method 1: Azure Developer CLI (`azd`)

```bash
# Initialize (first time)
azd init

# Deploy everything
azd up

# Post-deploy: upload team configs
# (automatically run via post-deploy hook)
```

The `azure.yaml` / `azure_custom.yaml` defines:
- Pre-package hooks for frontend build
- Post-deploy hooks for team config upload + dataset indexing

✅ *Verified in code:* `azure.yaml`, `azure_custom.yaml`

### Method 2: Production Deployment Script

```bash
bash infra/scripts/deploy_prod.sh --confirm
```

This script (`infra/scripts/deploy_prod.sh`, 424 lines) performs:

1. **Build** Docker images for Backend + MCP
2. **Push** to ACR
3. **Verify** images exist in registry
4. **Create staging slot** on App Service
5. **Deploy** containers to staging
6. **Health check** staging endpoint
7. **Promote** staging → production (slot swap)
8. **Rollback** if health check fails

✅ *Verified in code:* `infra/scripts/deploy_prod.sh`

### Method 3: Manual Deployment

See [docs/ManualAzureDeployment.md](../ManualAzureDeployment.md) for step-by-step manual instructions.

---

## Post-Deployment Steps

### 1. Upload Team Configurations

```bash
python infra/scripts/upload_team_config.py
```

Uploads JSON team definitions from `data/agent_teams/` to the backend API.

### 2. Index Datasets

```bash
python infra/scripts/index_datasets.py
```

Indexes Blob container files into Azure AI Search for RAG-based teams (Retail, RFP, Contract Compliance).

### 3. Assign Roles

```bash
bash infra/scripts/cosmosdb_and_ai_user_role_assignment.sh
```

Assigns Cosmos DB and Azure AI User roles to service identities.

### 4. Configure Auth (Optional)

See [docs/azure_app_service_auth_setup.md](../azure_app_service_auth_setup.md) for EasyAuth configuration.

✅ *Verified in code:* `infra/scripts/`

---

## Environments

| Environment | Purpose | Config Source |
|---|---|---|
| **Local** | Development | `.env` files in each service |
| **Staging** | Pre-production validation | Container Apps staging slot / App Service staging slot |
| **Production** | Live deployment | Container Apps + App Service with slot swaps |

🔍 *Inferred from:* `deploy_prod.sh` staging/promote flow

---

## Config & Secrets Expectations

### At Deploy Time

| Config | How It's Set |
|---|---|
| Azure resource endpoints | Bicep outputs → Container Apps env vars |
| AI Search API key | Key Vault → Container Apps secret |
| QBO credentials | Container Apps secrets (manual or Key Vault reference) |
| Cosmos DB access | Managed Identity (preferred) |
| OpenAI connection | Container Apps env vars |
| Auth settings | Container Apps env vars / App Service auth config |

### Runtime Configuration

| Config | Location | Updated How |
|---|---|---|
| Team configs | Cosmos DB (via API) | `upload_team_config.py` or UI upload |
| Client mappings | `config/clients.json` | File edit + redeploy |
| Rule configs | Per-client in `ClientRulesConfig` | Code change + redeploy |
| Search indexes | Azure AI Search | `index_datasets.py` |

---

## Monitoring & Logging

### Current State

| Component | Tool | What It Captures |
|---|---|---|
| **Backend traces** | OpenTelemetry → App Insights | Request traces, spans, `x-trace-id` |
| **Container logs** | Log Analytics | stdout/stderr from containers |
| **App Service logs** | App Service diagnostics | Frontend serving logs |
| **Azure resource metrics** | Azure Monitor | CPU, memory, request count, latency |
| **AI Foundry usage** | Azure OpenAI metrics | Token usage, request count |

✅ *Verified in code:* `docs/architecture/controls.md` (observability section)

### Recommended Monitoring

| Alert | Trigger | Priority |
|---|---|---|
| Backend container restarts | Restart count > 3 in 5min | High |
| QBO OAuth failures | 401/403 from Intuit API | High |
| Rules engine exceptions | Unhandled errors in rule evaluation | High |
| Review run stuck in non-terminal state | Run age > 10min without completion | Medium |
| WebSocket connection drops | Abnormal close rate > threshold | Medium |
| High AI token usage | Unusual spike in GPT-4.1 consumption | Low |

⚠️ **Needs verification** — specific alert rules may not be configured yet.

---

## Runbook Basics

### Health Check

```bash
# Check backend health
curl -sS https://<backend-url>/health | jq .

# Check QBO status for a client
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend-url>/api/qbo/status?client_id=blackbird" | jq .

# Check MCP server
curl -sS https://<mcp-url>/health | jq .
```

### Common Operations

| Operation | Command |
|---|---|
| View container logs | `az containerapp logs show -n <app-name> -g <rg>` |
| Restart backend | `az containerapp revision restart -n <app-name> -g <rg> --revision <rev>` |
| Scale backend | `az containerapp update -n <app-name> -g <rg> --min-replicas <n>` |
| Check deployment status | `az containerapp show -n <app-name> -g <rg> --query properties.provisioningState` |
| Swap App Service slots | `az webapp deployment slot swap -n <app-name> -g <rg> --slot staging` |

### Smoke Test After Deploy

Use the [MVP1 Smoke Checklist](../architecture/mer-mvp1-smoke-checklist.md) for post-deployment validation.
