# QBO Integration — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified in code unless otherwise tagged

---

## Overview

QuickBooks Online (QBO) is the primary data source for the MER Review Agent. The integration handles OAuth2 authentication, token management, and report fetching for balance sheet review.

---

## Architecture

```
Frontend                Backend                    QBO (Intuit)
   │                      │                           │
   │  QBO Connect popup   │                           │
   ├─────────────────────>│  GET /api/qbo/connect/prepare
   │                      ├──────────────────────────>│  OAuth2 authorize
   │                      │<──────────────────────────│  Callback + auth code
   │                      │  GET /api/qbo/callback    │
   │                      ├──────────────────────────>│  Exchange code for tokens
   │                      │<──────────────────────────│  Access + refresh tokens
   │                      │  Store tokens → Cosmos DB │
   │  qbo_connected=1     │                           │
   │<─────────────────────│                           │
   │                      │                           │
   │  (During review run) │                           │
   │                      ├──────────────────────────>│  GET /v3/company/{realmId}/reports/BalanceSheet
   │                      │<──────────────────────────│  JSON report
   │                      ├──────────────────────────>│  GET /v3/company/{realmId}/query?query=...
   │                      │<──────────────────────────│  Accounts list
```

---

## Auth Flow

### OAuth2 Authorization Code Flow

1. **User clicks "Authenticate in QBO"** in the frontend `QboConnectButton` popover
2. **Frontend opens** `/qbo/connect?client_id={client_id}` in a new tab
3. **`QboConnectPage`** calls `GET /api/qbo/connect/prepare` with the user's bearer token
4. **Backend** generates Intuit OAuth2 authorization URL with:
   - `client_id` (Intuit app ID, from `QBO_CLIENT_ID` env var)
   - `redirect_uri` (from `QBO_REDIRECT_URI` env var)
   - `scope` (from `QBO_OAUTH_SCOPES`, typically `com.intuit.quickbooks.accounting`)
   - `state` parameter (includes user identity + CSRF protection)
5. **User completes consent** on Intuit's OAuth page
6. **Intuit redirects** to `/api/qbo/callback` with auth code + state
7. **Backend** exchanges auth code for access + refresh tokens
8. **Tokens are stored** in Cosmos DB via `QboOAuthStateStore`
9. **Callback page** communicates back to opener via `postMessage` + `localStorage` event

✅ *Verified in code:*
- Frontend: `src/frontend/src/pages/QboConnectPage.tsx`, `src/frontend/src/pages/QboCallbackPage.tsx`
- Backend: `src/backend/api/qbo.py`
- Connector: `src/backend/connectors/qbo/client.py`, `src/backend/connectors/qbo/token_store.py`

### Token Storage

| Store | What | When |
|---|---|---|
| **Cosmos DB** | Access token, refresh token, realm_id, expiry | Production (preferred) |
| **In-memory fallback** | Same data, process-scoped | ⚠️ Dev fallback — **unreliable in multi-instance deployments** |

⚠️ **Known risk:** The Cosmos fallback was historically allowed to silently fail, causing intermittent OAuth state loss in Container Apps (multi-replica). This was identified in `docs/architecture/mer-review-agent-spec.md` §8.

### Token Refresh

✅ *Verified line-by-line in:* `src/backend/connectors/qbo/auth.py`

- Access tokens expire (typically 1 hour for Intuit)
- **Pre-call check:** `ensure_access_token_valid(config)` is called at the top of `qbo_get()` — if `token_expires_at` has passed, it triggers `refresh_access_token()` before the first request
- **Reactive refresh:** If a QBO API call returns **HTTP 401** and no refresh has happened yet in this call chain, `refresh_access_token()` is called and the request is retried **once**
- **Refresh mechanics:**
  - POST to `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`
  - Body: `grant_type=refresh_token&refresh_token=<token>`
  - Auth header: `Basic base64(client_id:client_secret)`
  - Timeout: 30 seconds
- **Token persistence after refresh:**
  1. Updates `os.environ` in-process (`QBO_ACCESS_TOKEN`, `QBO_REFRESH_TOKEN`, `QBO_TOKEN_EXPIRES_AT`)
  2. If `get_client_store_mode() == "cosmos"` → writes to Cosmos DB via `update_refresh_token_for_realm()`; logs warning on failure
  3. Otherwise → updates `.env` file in-place + writes to `.qbo_tokens.json` via `save_tokens()`
- **Expiry parsing:** Supports both ISO 8601 strings and Unix epoch timestamps; treats unparseable values as expired

---

## Retry & Backoff Behavior

✅ *Verified line-by-line in:* `src/backend/connectors/qbo/client.py` → `qbo_get()`

### Parameters

| Parameter | Default | Description |
|---|---|---|
| `timeout_seconds` | `30` | Per-request socket timeout passed to `urlopen()` |
| `max_retries` | `3` | Maximum retry attempts (configurable per call) |

### Retry Loop

```
Initial state: retries=0, refreshed=False, backoff=0.5s

┌─── Loop ────────────────────────────────────────────────────────┐
│                                                                 │
│  Build URL → send GET with Bearer token                        │
│                                                                 │
│  On HTTPError:                                                  │
│    401 AND not yet refreshed → refresh token, retry (no count)  │
│    429 | 500 | 502 | 503 | 504 AND retries < max_retries →     │
│        sleep(backoff), retries++, backoff *= 2, retry           │
│    Else → raise QBOHttpError(status, reason, body)              │
│                                                                 │
│  On URLError (network-level / DNS / timeout):                   │
│    retries < max_retries →                                      │
│        sleep(backoff), retries++, backoff *= 2, retry           │
│    Else → raise QBOHttpError(0, message)                        │
│                                                                 │
│  On success → return JSON dict                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Backoff Schedule (Worst Case)

| Attempt | Wait Before | Cumulative |
|---|---|---|
| 1 (initial) | 0 s | 0 s |
| 2 (retry 1) | 0.5 s | 0.5 s |
| 3 (retry 2) | 1.0 s | 1.5 s |
| 4 (retry 3) | 2.0 s | 3.5 s |

**Max total wait:** 3.5 seconds of sleep + up to 4 × 30 s request timeout = ~123.5 s worst case.

### Key Behaviors

- **Exponential backoff:** starts at 0.5 s, doubles each retry (`0.5 → 1.0 → 2.0`)
- **No jitter:** backoff is deterministic (no random component)
- **401 does not consume a retry count** — it gets one refresh attempt, then falls through to normal retry logic if the refreshed token also fails
- **Network errors** (DNS, timeout, connection refused) follow the same backoff as server errors
- **Status 400, 403, 404, 422** are **not retried** — they raise immediately
- **All retried statuses:** 429, 500, 502, 503, 504

### Report-Level Fallback

✅ *Verified in:* `src/backend/connectors/qbo/reports.py` → `fetch_transaction_list_by_account()`

When `TransactionListByAccount` returns 400 or 404, the code falls back to the simpler `TransactionList` endpoint with `include_split_detail` removed. This is not a retry but a graceful degradation for QBO realms that don't support the split-detail report.

---

## API Data Used

### Reports Fetched During Review

| QBO Report | Endpoint Pattern | Used For |
|---|---|---|
| **Balance Sheet** | `GET /v3/company/{realmId}/reports/BalanceSheet` | Primary review data — multi-period balances |
| **Profit & Loss** | `GET /v3/company/{realmId}/reports/ProfitAndLoss` | Revenue/expense totals for certain rules |
| **Accounts List** | `GET /v3/company/{realmId}/query?query=select * from Account` | Chart of Accounts with types/subtypes |
| **AP Aging Summary** | `GET /v3/company/{realmId}/reports/AgedPayables` | AP aging totals |
| **AP Aging Detail** | `GET /v3/company/{realmId}/reports/AgedPayableDetail` | AP line-item aging |
| **AR Aging Summary** | `GET /v3/company/{realmId}/reports/AgedReceivables` | AR aging totals |
| **AR Aging Detail** | `GET /v3/company/{realmId}/reports/AgedReceivableDetail` | AR line-item aging |
| **Trial Balance** | `GET /v3/company/{realmId}/reports/TrialBalance` | Account balances for reconciliation |
| **Transaction List** | `GET /v3/company/{realmId}/reports/TransactionList` | Register details for bank reconciliation |

✅ *Verified in code:* `src/backend/connectors/qbo/reports.py`, `src/mcp_server/services/finance_service.py` (MCP tool names reference these reports)

### MCP Finance Tools (QBO-Related)

The MCP FinanceService exposes these QBO tools that proxy to backend APIs:

| MCP Tool | Backend Endpoint | Purpose |
|---|---|---|
| `check_qbo_connection` | `GET /api/qbo/status` | Verify QBO connection status |
| `get_qbo_balance_sheet` | `GET /api/qbo/reports/balance-sheet` | Fetch balance sheet |
| `get_qbo_profit_and_loss` | `GET /api/qbo/reports/profit-and-loss` | Fetch P&L |
| `get_qbo_accounts` | `GET /api/qbo/reports/accounts` | Fetch chart of accounts |
| `get_qbo_ap_aging_summary` | `GET /api/qbo/reports/ap-aging-summary` | Fetch AP aging |
| `get_qbo_ar_aging_summary` | `GET /api/qbo/reports/ar-aging-summary` | Fetch AR aging |
| `get_qbo_trial_balance` | `GET /api/qbo/reports/trial-balance` | Fetch trial balance |
| `get_qbo_transaction_list` | `GET /api/qbo/reports/transaction-list` | Fetch transactions |

✅ *Verified in code:* `src/mcp_server/services/finance_service.py`

---

## Client Configuration

Client-to-QBO mapping is in `config/clients.json`:

```json
{
  "clients": {
    "blackbird": {
      "realm_id": "193514892490929",
      "counterparties": []
    }
  }
}
```

- `realm_id` — QBO company identifier (used in API calls)
- `counterparties` — related companies for intercompany reconciliation rules
- Multiple client names can map to the same `realm_id`

✅ *Verified in code:* `config/clients.json`

---

## Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `QBO_ENV` | QBO environment (`sandbox` or `production`) | `production` |
| `QBO_CLIENT_ID` | Intuit OAuth app client ID | (secret) |
| `QBO_CLIENT_SECRET` | Intuit OAuth app client secret | (secret) |
| `QBO_REALM_ID` | Default QBO realm ID | `193514892490929` |
| `QBO_REDIRECT_URI` | OAuth callback URL | `https://{backend}/api/qbo/callback` |
| `QBO_OAUTH_SCOPES` | OAuth scopes | `com.intuit.quickbooks.accounting` |

✅ *Verified in code:* `src/backend/.env.qbo`

---

## Known API Limitations

| Limitation | Impact | Status |
|---|---|---|
| QBO rate limits (typically 500 req/min per realm) | May throttle large review runs | ✅ Handled — 429 triggers exponential backoff (0.5 s × 2^n, up to 3 retries) |
| QBO report date ranges | Must specify accounting period correctly | ✅ Handled in adapters |
| QBO sandbox data quality | Test data may not cover all account types | 🔍 Inferred |
| OAuth token expiry (1hr access, 100-day refresh) | Requires transparent refresh | ✅ Pre-call check + reactive 401 refresh in `qbo_get()` |
| Multi-currency support | QBO multi-currency may affect balance parsing | ⚠️ Needs verification |
| No jitter in backoff | Under concurrent load, retries may cluster | ✅ Verified — deterministic backoff, consider adding jitter for production |

---

## Failure Modes

| Scenario | Current Handling | Status |
|---|---|---|
| QBO connection expired | Frontend shows `QboStatusBanner` warning; user must re-authenticate | ✅ |
| OAuth callback failure | Error displayed in callback page; user retries | ✅ |
| Token refresh failure | Raises `QBOAuthError`; if during `qbo_get()` the 401 path runs, it raises `QBOHttpError` | ✅ Verified |
| QBO API 429 (rate limit) | Retried up to 3× with exponential backoff (0.5→1→2 s) | ✅ Verified |
| QBO API 5xx (500, 502, 503, 504) | Retried up to 3× with exponential backoff; then raises `QBOHttpError` which surfaces as review run `status=failed` | ✅ Verified |
| QBO API 400/403/404 | Raised immediately as `QBOHttpError` (no retry) | ✅ Verified |
| Network error (DNS, timeout, connection refused) | Retried up to 3× with exponential backoff; then raises `QBOHttpError(status=0)` | ✅ Verified |
| Cosmos token store unavailable | Falls back to in-memory + `.env` file (risky in multi-instance) | ⚠️ Known risk |
| Invalid realm_id | QBO returns 401/403; no retry (non-retryable status) | ✅ Verified |
| Token refresh endpoint failure | `QBOAuthError` raised; no retry on the refresh call itself | ✅ Verified |

---

## Connection Status Checking

The frontend uses a lightweight status check rather than live Intuit probe:

```
Frontend: useQboStatus hook
  → GET /api/qbo/status?client_id={id}
  → Backend checks Cosmos for stored tokens
  → Returns { connected: bool, client_id, realm_id }
```

This avoids hitting QBO rate limits on every page load.

✅ *Verified in code:* `src/frontend/src/hooks/useQboStatus.ts` (comment explains this design choice)
