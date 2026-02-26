# Operational Runbook — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified from code, infra scripts, and smoke checklist
> **See also:** [deployment-operations.md](deployment-operations.md), [error-handling.md](error-handling.md), [api-reference.md](api-reference.md)

---

## Quick Reference

| Action | Command |
|---|---|
| Backend health | `curl -sS https://<backend>/health \| jq .` |
| Readiness probe | `curl -sS https://<backend>/readyz \| jq .` |
| QBO status | `curl -sS -H "Authorization: Bearer $TOKEN" "https://<backend>/api/qbo/status?client_id=<id>" \| jq .` |
| QBO live validate | `curl -sS -H "Authorization: Bearer $TOKEN" "https://<backend>/api/qbo/validate?client_id=<id>" \| jq .` |
| Drive status | `curl -sS -H "Authorization: Bearer $TOKEN" "https://<backend>/api/drive/status?client_id=<id>" \| jq .` |
| View container logs | `az containerapp logs show -n <app> -g <rg> --follow` |
| Restart backend | `az containerapp revision restart -n <app> -g <rg> --revision <rev>` |
| Scale replicas | `az containerapp update -n <app> -g <rg> --min-replicas <n> --max-replicas <m>` |
| Swap slots (frontend) | `az webapp deployment slot swap -n <app> -g <rg> --slot staging` |

---

## Decision Trees

### DT-1: Review Run Not Completing

```
Review run status?
├── "queued" for > 2 minutes
│   ├── Check backend container logs for startup errors
│   │   → az containerapp logs show -n <backend-app> -g <rg> --follow
│   ├── Container crashing?
│   │   → Yes: Check memory/CPU limits, recent image changes
│   │   → No: Check if run_in_threadpool is blocked (thread exhaustion)
│   └── Fix: Restart backend container, then re-submit run
│
├── "running" for > 10 minutes
│   ├── Which phase is stuck? Check logs for:
│   │   - "balance_sheet_fetch_start" → Stuck fetching from QBO
│   │   - "balance_sheet.team_assembly" → Config resolution issue
│   │   - "balance_sheet.rules" → Rules evaluation hung
│   │   - "balance_sheet.report" → Artifact storage issue
│   ├── QBO fetch hung?
│   │   → Check QBO rate limits (429s in logs)
│   │   → Verify QBO connection: GET /api/qbo/validate?client_id=<id>
│   │   → QBO down? Wait and retry
│   ├── Blob storage timeout?
│   │   → Check AZURE_STORAGE_ACCOUNT_URL / AZURE_STORAGE_ACCOUNT_NAME
│   │   → Verify managed identity has Storage Blob Data Contributor role
│   └── Fix: If truly stuck, the run cannot be cancelled (no API for it).
│       Start a new run; the stuck run will eventually time out.
│
├── "raw" (expecting "fetched")
│   ├── NormalizationAgent hasn't called /normalize yet
│   │   → Check agent orchestration logs
│   │   → Manual: POST /api/reviews/balance-sheet/{run_id}/normalize
│   └── Normalization failed silently?
│       → Check run record error field
│
├── "fetched" (expecting "done")
│   ├── RulesAgent hasn't called /run-rules yet
│   │   → Check agent orchestration logs
│   │   → Manual: POST /api/reviews/balance-sheet/{run_id}/run-rules
│   └── Rules evaluation failed?
│       → Check run record error field
│
└── "failed"
    ├── Check record.error for the exception message
    ├── Common failures:
    │   - "QBO connection missing" → Re-connect QBO
    │   - "QBO HTTP 401" → Token expired, re-authenticate
    │   - "QBO HTTP 429" → Rate limited after 3 retries, wait and retry
    │   - "Blob download failed" → Storage connectivity issue
    │   - Rule evaluation error → Check specific rule in logs
    └── Fix: Address root cause, then start a new run
```

### DT-2: QBO Connection Issues

```
GET /api/qbo/status?client_id=<id>
├── connected: false, reason: "client_id is required"
│   └── Fix: Pass a valid client_id
│
├── connected: false, reason: "no record found"
│   ├── Is client_id correct?
│   │   → Check suggested_client_ids in response
│   │   → GET /api/qbo/debug/clients (if debug enabled)
│   ├── Never connected?
│   │   → Start OAuth: GET /api/qbo/connect/start?client_id=<id>
│   └── Was connected before?
│       → Record may have been deleted from Cosmos
│       → Re-connect via OAuth flow
│
├── connected: false, reason: "missing realm_id or refresh_token"
│   └── Partial connection → Re-connect via OAuth flow
│
├── connected: true → Now validate live:
│   GET /api/qbo/validate?client_id=<id>
│   ├── live: true → Connection is healthy ✅
│   ├── live: false, reason: "token_expired"
│   │   └── Re-authenticate: OAuth flow will get new refresh token
│   ├── live: false, reason: "no_refresh_token"
│   │   └── Record exists but refresh_token missing → Re-connect
│   └── live: false, reason: "probe_failed"
│       ├── Check detail field for specific error
│       ├── QBO service down? → Wait and retry
│       └── Network issue? → Check container egress/DNS
```

### DT-3: Drive Connection Issues

```
GET /api/drive/status?client_id=<id>
├── connected: false, reason: "Missing required environment variable: DRIVE_CLIENT_ID"
│   └── Fix: Set DRIVE_CLIENT_ID and DRIVE_CLIENT_SECRET env vars
│
├── connected: false, reason: "Missing required environment variable: DRIVE_REFRESH_TOKEN"
│   └── Fix: Add refresh_token to client record or env var
│
├── connected: true, folder_accessible: false
│   ├── reason contains "401" → Token expired, needs re-auth
│   ├── reason contains "403" → Insufficient permissions on folder
│   │   └── Fix: Share folder with the OAuth user or verify scopes
│   ├── reason contains "404" → Invalid root_folder_id
│   │   └── Fix: Verify folder ID exists and is shared
│   └── reason contains network error → Check egress connectivity
│
├── connected: true, folder_accessible: true → Healthy ✅
│   ├── evidence_manifest_file_id: null
│   │   └── ⚠️ Drive-only rules will be disabled
│   └── evidence_manifest_file_id: present → Full evidence flow available
│
└── connected: true, folder_accessible: null
    └── No root_folder_id configured → Only direct file_id access works
```

### DT-4: Review Results Unexpected

```
Review completed (status=done) but results seem wrong?
│
├── All rules show "not_applicable"
│   ├── Are Drive-only rules disabled?
│   │   → Check: DRIVE_EVIDENCE_ENABLED=true?
│   │   → Check: evidence_manifest_file_id configured?
│   ├── Client rules config disabling rules?
│   │   → Check ClientRulesConfig for the client
│   └── Balance sheet data empty?
│       → Check snapshot: GET /api/reviews/snapshots/content?snapshot_key=...
│
├── Rules show "needs_review" when expected "pass"
│   ├── Missing evidence documents?
│   │   → Check hitl_requests in the run record
│   │   → Upload required evidence via Drive
│   ├── Threshold configuration?
│   │   → Check rule-specific config thresholds
│   └── Data quality issue?
│       → Check raw QBO data in snapshots
│
├── Rules show "fail" when expected "pass"
│   ├── Check findings[].summary for the specific rule
│   ├── Check findings[].details for calculation breakdown
│   ├── Verify QBO data is correct for the period
│   └── Compare with manual review
│
└── Balance sheet view shows wrong periods
    ├── Check period_end parameter used in the run
    ├── Check balance_sheet_view.period_columns
    └── Prior periods depend on QBO historical data availability
```

---

## Operational Procedures

### OP-1: Post-Deploy Smoke Test

Follow the [MVP1 Smoke Checklist](../architecture/mer-mvp1-smoke-checklist.md):

```bash
# 1. Set env vars
export BACKEND_BASE_URL="https://<backend>"
export AUTH_TOKEN="<bearer-token>"
export CLIENT_ID="blackbird_fabrics"
export PERIOD_END="2025-01-31"

# 2. Health check
curl -sS "$BACKEND_BASE_URL/readyz" | jq .
# Expected: { "status": "ready" }

# 3. QBO status
curl -sS -H "Authorization: Bearer $AUTH_TOKEN" \
  "$BACKEND_BASE_URL/api/qbo/status?client_id=$CLIENT_ID" | jq .
# Expected: connected: true

# 4. Start review run
RUN_RESPONSE=$(curl -sS -X POST \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "$BACKEND_BASE_URL/api/reviews/balance-sheet/run" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"period_end\":\"$PERIOD_END\"}")
echo "$RUN_RESPONSE" | jq .
RUN_ID=$(echo "$RUN_RESPONSE" | jq -r '.run_id')

# 5. Poll until done (timeout after 5 minutes)
for i in $(seq 1 30); do
  STATUS=$(curl -sS -H "Authorization: Bearer $AUTH_TOKEN" \
    "$BACKEND_BASE_URL/api/reviews/balance-sheet/runs/$RUN_ID" | jq -r '.status')
  echo "Attempt $i: status=$STATUS"
  if [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 10
done

# 6. Verify terminal state
curl -sS -H "Authorization: Bearer $AUTH_TOKEN" \
  "$BACKEND_BASE_URL/api/reviews/balance-sheet/runs/$RUN_ID" | jq '{status, totals, error}'
```

**Evidence to capture per smoke run:**
- UTC timestamp
- `client_id` and `period_end`
- `run_id`
- Terminal status
- `x-trace-id` from response headers (for App Insights correlation)

---

### OP-2: Restart Backend Container

```bash
# List revisions
az containerapp revision list -n <backend-app> -g <rg> -o table

# Restart active revision
az containerapp revision restart \
  -n <backend-app> -g <rg> \
  --revision <revision-name>
```

**When to restart:**
- Thread pool exhaustion (runs stuck in "queued")
- Memory leak symptoms (increasing memory over time)
- After manual env var / secret changes

**⚠️ Impact:** In-flight review runs will fail. In-memory OAuth state (dev mode only) will be lost.

---

### OP-3: Scale Backend

```bash
# Check current scale
az containerapp show -n <backend-app> -g <rg> \
  --query "properties.template.scale" -o json

# Scale up
az containerapp update -n <backend-app> -g <rg> \
  --min-replicas 2 --max-replicas 5

# Scale down
az containerapp update -n <backend-app> -g <rg> \
  --min-replicas 1 --max-replicas 3
```

**Scaling considerations:**
- Each replica can handle multiple concurrent review runs (FastAPI async)
- QBO rate limits are per-realm, not per-replica — scaling won't help with 429s
- Cosmos token storage is shared — safe across replicas
- In-memory fallback is NOT shared — risky with >1 replica

---

### OP-4: Re-Connect QBO for a Client

```bash
# 1. Check current status
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend>/api/qbo/validate?client_id=$CLIENT_ID" | jq .

# 2. If live: false, initiate OAuth flow
# Option A: Browser flow
# Navigate to: https://<frontend>/qbo/connect?client_id=$CLIENT_ID
# Complete Intuit consent

# Option B: API flow (for automation)
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend>/api/qbo/connect/prepare?client_id=$CLIENT_ID" | jq .
# Returns authorization_url → open in browser → complete consent

# 3. Verify reconnection
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend>/api/qbo/validate?client_id=$CLIENT_ID" | jq .
# Expected: connected: true, live: true
```

---

### OP-5: Deploy New Version

```bash
# Option 1: Full deploy via azd
azd up

# Option 2: Production deploy with staging
bash infra/scripts/deploy_prod.sh --confirm

# Option 3: Backend-only image update
az containerapp update -n <backend-app> -g <rg> \
  --image <acr>.azurecr.io/macae-backend:<tag>
```

**Post-deploy checklist:**
1. ✅ Health check passes (`/readyz`)
2. ✅ QBO status check for known clients
3. ✅ Submit a test review run
4. ✅ Verify run reaches `done` status
5. ✅ Upload team configs if changed (`python infra/scripts/upload_team_config.py`)

---

### OP-6: Investigate Failed Review Run

```bash
# 1. Get the run record
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend>/api/reviews/balance-sheet/runs/$RUN_ID" | jq '{status, error, started_at, completed_at}'

# 2. Check container logs (use x-trace-id for correlation)
az containerapp logs show -n <backend-app> -g <rg> \
  --follow --tail 200 | grep "$RUN_ID"

# 3. Check App Insights (if configured)
# Query: traces | where message contains "<run_id>"

# 4. Check what artifacts were saved
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend>/api/reviews/balance-sheet/runs/$RUN_ID/snapshots" | jq .
```

**Common failure patterns:**

| Error Message | Root Cause | Fix |
|---|---|---|
| `QBO connection missing for client_id` | Client never connected or record deleted | Re-connect via OAuth |
| `QBO HTTP 401: Unauthorized` | Access token expired and refresh failed | Re-authenticate |
| `QBO HTTP 429` after retries | Rate limited (3 retries exhausted) | Wait 60s, retry |
| `QBO HTTP 503` after retries | QBO service outage | Wait, check Intuit status page |
| `Blob download failed` | Storage account unreachable | Check AZURE_STORAGE_ACCOUNT_URL, managed identity roles |
| `Missing required environment variable` | Env var not set in container config | Update container env vars, restart |
| `Unable to persist QBO connection` | Cosmos DB unreachable | Check COSMOSDB_ENDPOINT, managed identity |

---

## Monitoring & Alerting

### Key Metrics to Monitor

| Metric | Source | Threshold | Severity |
|---|---|---|---|
| Backend container restarts | Container Apps metrics | > 3 in 5 min | 🔴 High |
| HTTP 5xx rate | App Insights / access logs | > 5% of requests | 🔴 High |
| QBO 401 errors | App logs (`QBOHttpError`) | Any sustained occurrence | 🟡 Medium |
| QBO 429 errors | App logs | > 10 in 5 min | 🟡 Medium |
| Review runs stuck > 10 min | Cosmos query on run records | Any | 🟡 Medium |
| Review run failure rate | App logs / run records | > 20% | 🟡 Medium |
| Memory usage | Container Apps metrics | > 80% of limit | 🟡 Medium |
| Cosmos RU consumption | Cosmos DB metrics | > 80% of provisioned | 🟡 Medium |

### Log Patterns to Watch

```bash
# Failed review runs
az containerapp logs show -n <app> -g <rg> | grep "balance_sheet.*failed"

# QBO errors
az containerapp logs show -n <app> -g <rg> | grep "QBOHttpError\|QBOAuthError"

# Drive errors
az containerapp logs show -n <app> -g <rg> | grep "DriveHttpError\|DriveAuthError"

# Token refresh failures
az containerapp logs show -n <app> -g <rg> | grep "Token refresh failed\|token_expired"

# Cosmos failures
az containerapp logs show -n <app> -g <rg> | grep "Cosmos.*fail\|cosmos.*error"
```

### App Insights KQL Queries

```kql
// Failed review runs in last 24h
traces
| where timestamp > ago(24h)
| where message contains "balance_sheet" and message contains "failed"
| project timestamp, message, operation_Id
| order by timestamp desc

// QBO error rate by status code
traces
| where timestamp > ago(1h)
| where message contains "QBO HTTP"
| extend status = extract("QBO HTTP (\\d+)", 1, message)
| summarize count() by status, bin(timestamp, 5m)
| render timechart

// Slow review runs (>5 min)
traces
| where timestamp > ago(24h)
| where message contains "balance_sheet_rules_done"
| extend duration_ms = todouble(extract("duration_ms=([\\d.]+)", 1, message))
| where duration_ms > 300000
| project timestamp, message, duration_ms
```

---

## Emergency Procedures

### EMRG-1: QBO OAuth Tokens All Expired

**Symptoms:** All review runs failing with 401, `/api/qbo/validate` returns `live: false` for all clients.

**Cause:** Intuit refresh token expired (100-day lifetime) or revoked.

**Fix:**
1. For each client, re-initiate OAuth flow via browser
2. Verify each client: `GET /api/qbo/validate?client_id=<id>`
3. Re-run any failed review runs

---

### EMRG-2: Cosmos DB Unavailable

**Symptoms:** 503 errors on OAuth callbacks, review runs fail with persistence errors.

**Fix:**
1. Check Cosmos DB status in Azure portal
2. Verify managed identity role assignments
3. Check COSMOSDB_ENDPOINT env var
4. If RU throttled: increase provisioned throughput
5. If region outage: failover to secondary (if configured)

---

### EMRG-3: Backend Container Crash Loop

**Symptoms:** Health check failing, container restarting repeatedly.

**Fix:**
1. `az containerapp logs show -n <app> -g <rg> --tail 100` — find crash reason
2. Common causes: missing env vars, bad image, OOM
3. Rollback to previous revision: `az containerapp revision activate -n <app> -g <rg> --revision <previous>`
4. Fix root cause, push new image, update container app

---

### EMRG-4: QBO Rate Limiting (Sustained)

**Symptoms:** Multiple runs failing with 429 after retry exhaustion.

**Fix:**
1. Check how many concurrent runs are hitting the same realm
2. Stagger run submissions (no API for this — operational discipline)
3. QBO rate limit is typically 500 req/min per realm
4. Consider reducing `max_retries` sleep time if runs are timing out
5. If truly rate-limited: wait 60 seconds, then retry
