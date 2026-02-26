# Security & Privacy — MER Review Agent

> **Status:** Living document
> **Confidence:** Mixed — combines code-verified facts with recommended best practices
> **See also:** [docs/architecture/controls.md](../architecture/controls.md) (detailed security controls)

---

## Sensitive Data Handled

| Data Category | Sensitivity | Where It Lives |
|---|---|---|
| QBO OAuth tokens (access + refresh) | **Critical** | Cosmos DB (production), in-memory (dev fallback) |
| QBO financial reports (balance sheets, P&L, aging) | **High** | Cosmos DB (run records), Blob Storage (snapshots) |
| Client identifiers and realm IDs | **High** | `config/clients.json`, Cosmos DB |
| User identity (email, tenant, object ID) | **Medium** | Bearer tokens, EasyAuth headers, plan records |
| Review findings and rule results | **Medium** | Cosmos DB (review runs), API responses |
| Azure service keys (AI Search API key) | **Critical** | Key Vault |
| QBO client secret | **Critical** | Environment variable / Key Vault |
| Google service account credentials | **Critical** | ⚠️ Needs verification — likely env var or Key Vault |

---

## Access Controls

### Implemented ✅

| Control | Implementation | Code Reference |
|---|---|---|
| **Azure AD authentication** | EasyAuth (App Service) + MSAL + Bearer token validation | `src/backend/auth/`, `src/frontend/src/api/config.tsx` |
| **User identity resolution** | Resolved from bearer token or EasyAuth headers (`X-MS-CLIENT-PRINCIPAL-*`) | `src/backend/auth/` |
| **MCP auth forwarding** | User's bearer token forwarded from Backend → MCP → Backend fan-out | `src/mcp_server/services/finance_service.py` |
| **No client-side secrets** | All OAuth, token, and API key handling is server-side | Architecture boundary |
| **Key Vault for secrets** | Azure AI Search API key stored in Key Vault | `docs/architecture/controls.md` |
| **Managed Identity** | User-assigned MI for cross-service Azure access | `infra/main.bicep` |
| **Dev auth fallback** | `ALLOW_SAMPLE_USER_FALLBACK` allows bypassing auth in dev mode | `src/backend/.env.example` |
| **Container Apps secrets** | Runtime secrets injected via Container Apps config | `azure_custom.yaml` |

### Gaps / Recommended ⚠️

| Gap | Risk | Recommendation |
|---|---|---|
| **AI Search public endpoint** | Search index data accessible without VNet restriction | Enable private endpoint or IP restrictions |
| **Container Apps external ingress** | Backend/MCP endpoints publicly reachable | Add VNet integration + internal-only ingress |
| **EasyAuth header spoofing** | Without App Service trust, `X-MS-CLIENT-PRINCIPAL-*` headers can be forged | Validate JWT signature server-side (not just headers) |
| **QBO tokens in Cosmos without encryption-at-rest verification** | Tokens at rest may be readable by Cosmos admins | Verify Cosmos encryption-at-rest is enabled (default in Azure) |
| **No per-client authorization** | Users can potentially access any client's QBO data | Add client-level access control |
| **Refresh token scope** | QBO refresh tokens may grant broader access than needed | Review Intuit OAuth scopes |

✅ *Verified in code:* `docs/architecture/controls.md`

---

## Trust Boundaries

```
┌─────────────────────────────────────────────────────────┐
│ Browser (Untrusted)                                      │
│   Frontend SPA — no secrets, no direct external API      │
├──────────────── HTTPS + Bearer Token ───────────────────┤
│ Frontend App Service (Semi-Trusted)                      │
│   Static file server — EasyAuth gate                     │
├──────────────── REST + WebSocket ───────────────────────┤
│ Backend Container App (Trusted)                          │
│   FastAPI — validates tokens, owns business logic        │
│   Connectors — QBO OAuth, Drive service account          │
│   Rules Engine — deterministic, no IO                    │
├──────────────── Streamable HTTP + Bearer ───────────────┤
│ MCP Container App (Semi-Trusted)                         │
│   FastMCP — proxy layer, forwards auth to Backend        │
│   Never directly accesses external APIs                  │
├──────────────── Azure SDK + Managed Identity ───────────┤
│ Azure Managed Services (Trusted)                         │
│   Cosmos DB, Blob Storage, Key Vault, AI Foundry         │
├──────────────── HTTPS + OAuth2 ─────────────────────────┤
│ External APIs (External Trust)                           │
│   QBO (Intuit), Google Drive                             │
└─────────────────────────────────────────────────────────┘
```

✅ *Verified in code:* `docs/architecture/controls.md` (6 trust boundaries)

---

## Secret Management

### Current State

| Secret | Storage | Access Method |
|---|---|---|
| `AzureAISearchAPIKey` | Key Vault | SDK + Managed Identity |
| `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | Container Apps secrets / env var | Environment variable |
| QBO OAuth tokens (per-user) | Cosmos DB | Token store module |
| Google service account key | ⚠️ Unclear | ⚠️ Needs verification |
| Azure OpenAI key / connection string | Container Apps secrets | Environment variable |
| Cosmos DB connection | Managed Identity (preferred) | Azure SDK |

### Recommendations

1. **Migrate all secrets to Key Vault** — avoid environment variables for sensitive values where possible
2. **Rotate QBO client secret** on a regular schedule
3. **Audit Cosmos DB access** — ensure only Backend identity can read/write QBO tokens
4. **Add secret expiry monitoring** — alert when Key Vault secrets or QBO tokens approach expiry

---

## Logging & PII

### Current State

| Aspect | Implementation |
|---|---|
| **OpenTelemetry** | OTLP traces with `x-trace-id` correlation | 
| **Log Analytics** | Azure Monitor Log Analytics workspace |
| **App Insights** | Application Insights for metrics and traces |
| **Diagnostic settings** | Configured via Bicep |

✅ *Verified in code:* `docs/architecture/controls.md`, `src/backend/.env.example` (OTLP vars)

### PII Considerations

| Risk | Current Mitigation | Recommendation |
|---|---|---|
| User email in logs | ⚠️ Needs verification | Redact PII from structured logs |
| QBO financial data in traces | ⚠️ Needs verification | Ensure financial amounts are not logged at DEBUG level |
| Client names in log messages | ⚠️ Likely present | Use client_id references instead of names in logs |
| OAuth tokens in error logs | ⚠️ Needs verification | Add token redaction to error handlers |

---

## Risks & Recommended Next Steps

### High Priority

| Risk | Impact | Recommendation |
|---|---|---|
| **AI Search public access** | Data exfiltration of search indexes | Enable private endpoint |
| **No per-client authorization** | User A can review User B's clients | Add client-level RBAC |
| **QBO token in-memory fallback** | Token loss in multi-instance deployment | Remove fallback; require Cosmos |
| **Header spoofing potential** | Identity impersonation | Always validate JWT signature |

### Medium Priority

| Risk | Impact | Recommendation |
|---|---|---|
| **Container Apps external ingress** | Attack surface exposure | Enable VNet integration |
| **No rate limiting on review API** | Potential abuse / QBO rate limit exhaustion | Add per-user rate limiting |
| **Drive credentials management** | Unclear storage mechanism | Document and standardize |

### Low Priority

| Risk | Impact | Recommendation |
|---|---|---|
| **Secret rotation automation** | Operational burden | Implement Key Vault auto-rotation |
| **Audit logging for QBO access** | Compliance gap | Log all QBO API calls with user context |
| **PII in telemetry** | Privacy compliance | Add PII scrubbing to telemetry pipeline |

---

## Compliance Notes

⚠️ **Needs verification** — The following compliance considerations should be evaluated:

- **SOC 2 Type II** — if handling client financial data, audit controls may be required
- **Data residency** — Azure region selection affects where financial data is stored
- **Data retention** — review run data and QBO snapshots retention policy not defined
- **Right to deletion** — process for removing a client's data not documented
- **Third-party risk** — QBO and Google Drive are external dependencies with their own compliance posture
