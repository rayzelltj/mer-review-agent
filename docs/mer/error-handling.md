# Error Handling — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified line-by-line from source code
> **Source files:** `src/backend/connectors/qbo/client.py`, `src/backend/connectors/qbo/auth.py`, `src/backend/connectors/drive/client.py`, `src/backend/connectors/drive/auth.py`, `src/backend/api/qbo.py`, `src/backend/api/reviews.py`, `src/backend/api/drive.py`, `src/backend/api/qbo_data.py`

---

## Exception Hierarchy

```
RuntimeError
├── QBOHttpError(status, message, body)     # connectors/qbo/client.py
├── QBOAuthError(message, body)             # connectors/qbo/auth.py
├── DriveHttpError(status, message, body)   # connectors/drive/client.py
└── DriveAuthError(message, body)           # connectors/drive/auth.py

fastapi.HTTPException                       # All API routers
ValueError                                  # Config validation
```

---

## 1. QBO Connector Error Handling

### `qbo_get()` — HTTP Client

| QBO Response | Action | Retried? | Max Retries | Backoff |
|---|---|---|---|---|
| **200 OK** | Parse JSON, return | — | — | — |
| **401 Unauthorized** | Refresh token once, retry | Yes (1×) | — | No wait |
| **429 Too Many Requests** | Sleep + retry | Yes | 3 | 0.5s × 2^n |
| **500 Internal Server Error** | Sleep + retry | Yes | 3 | 0.5s × 2^n |
| **502 Bad Gateway** | Sleep + retry | Yes | 3 | 0.5s × 2^n |
| **503 Service Unavailable** | Sleep + retry | Yes | 3 | 0.5s × 2^n |
| **504 Gateway Timeout** | Sleep + retry | Yes | 3 | 0.5s × 2^n |
| **400 Bad Request** | Raise immediately | No | — | — |
| **403 Forbidden** | Raise immediately | No | — | — |
| **404 Not Found** | Raise immediately | No | — | — |
| **Network error** (DNS/timeout/refused) | Sleep + retry | Yes | 3 | 0.5s × 2^n |

**Exception raised:** `QBOHttpError(status, reason, body)` — `status=0` for network errors.

### `refresh_access_token()` — Token Refresh

| Failure | Exception | Retried? |
|---|---|---|
| HTTP error from Intuit token endpoint | `QBOAuthError(f"Token refresh failed: {code} {reason}", body)` | No |
| Network error during refresh | `QBOAuthError(f"Token refresh failed: {exc}")` | No |
| Missing fields in response | `QBOAuthError("Token refresh response missing required fields.", body)` | No |
| Cosmos write failure after refresh | Logged as warning; does NOT raise | N/A |

### Report-Level Fallbacks

| Function | Fallback | Trigger |
|---|---|---|
| `fetch_transaction_list_by_account()` | Falls back from `TransactionListByAccount` → `TransactionList` | 400 or 404 from primary endpoint |

---

## 2. Drive Connector Error Handling

### `_drive_get_bytes()` — HTTP Client

| Drive Response | Action | Retried? |
|---|---|---|
| **200 OK** | Return bytes | — |
| **401 Unauthorized** | Refresh token once, retry | Yes (1×) |
| **All other HTTP errors** | Raise immediately | **No** |
| **Network error** | Raise immediately | **No** |

**Key difference from QBO:** Drive client has **no retry/backoff** for 429/5xx errors. Failures propagate immediately.

**Exception raised:** `DriveHttpError(status, reason, body)` — `status=0` for network errors.

### `refresh_access_token()` — Drive Token Refresh

| Failure | Exception |
|---|---|
| HTTP error from Google token endpoint | `DriveAuthError(f"Drive token refresh failed: {code} {reason}", body)` |
| Network error | `DriveAuthError(f"Drive token refresh failed: {exc}")` |
| Invalid `expires_in` | `DriveAuthError("Drive token refresh returned invalid expires_in.", body)` |
| Missing `access_token` | `DriveAuthError("Drive token refresh response missing required fields.", body)` |
| Cosmos write failure | Silently swallowed (`except Exception: return`) |

---

## 3. API Router Error Codes

### QBO OAuth Router (`/api/qbo/*`)

| HTTP Status | Condition | Detail Message |
|---|---|---|
| **400** | Invalid or expired OAuth state | `"Invalid or expired state."` |
| **400** | State payload missing `created_at` | `"Invalid OAuth state payload."` |
| **400** | State TTL exceeded (>600s) | `"State expired."` |
| **401** | Missing/invalid auth header | `"Unauthorized"` |
| **403** | State user ≠ signed-in user | `"OAuth state does not match signed-in user."` |
| **404** | Debug endpoints disabled | `"Not found"` |
| **500** | Missing env var | `"Missing required environment variable: {name}"` |
| **502** | Token exchange failed | `"QBO OAuth token exchange failed."` |
| **502** | Invalid `expires_in` | `"OAuth token exchange returned invalid expires_in."` |
| **503** | OAuth state save to Cosmos failed | `"Unable to initialize QBO OAuth state store. Please retry."` |
| **503** | OAuth state read from Cosmos failed | `"Unable to read QBO OAuth state. Please retry."` |
| **503** | Token persistence failed | `"Unable to persist QBO connection. Please retry."` |

### QBO Data Router (`/api/qbo/data/*`)

| HTTP Status | Condition | Detail Message |
|---|---|---|
| **400** | Invalid `basis` | `"basis must be 'Accrual' or 'Cash'."` |
| **400** | Missing `client_id` (multi-client) | `"client_id is required when multiple QBO clients exist."` |
| **400** | Missing `transaction_id` | `"transaction_id is required"` |
| **401** | Missing auth | `"Unauthorized"` |
| **404** | Client not found in store | `"QBO client '{id}' not found."` (with `suggested_client_ids`) |
| **404** | Transaction not found | `"Transaction '{id}' was not found across supported entity types."` |
| **409** | QBO connection incomplete | `"QBO connection incomplete for client '{id}'."` |
| **500** | Config load failure | `"Unable to load QBO config: {exc}"` |
| **502** | QBO report API error | `"QBO report call failed ({name}): {exc} | response_body={body}"` |

### Reviews Router (`/api/reviews/*`)

| HTTP Status | Condition | Detail Message |
|---|---|---|
| **400** | Invalid storage key | `"storage key is required"`, `"storage key must start with '{prefix}/'"`, `"invalid storage key"` |
| **400** | Missing `client_id` for Cosmos | `"client_id is required for Cosmos token storage."` |
| **401** | Missing auth (EasyAuth mode) | `"Unauthorized"` |
| **403** | Storage key not in run's allowed set | `"Access denied for the provided storage key."` |
| **404** | Run not found | `"Run not found"` |
| **404** | No active run found | `"No active run found"` |
| **409** | QBO not connected | Dynamic: `"QBO connection missing for client_id '{id}'. ..."` (may include suggestions) |
| **409** | Run still in progress | `"Run is still in progress. Wait and retry."` |
| **409** | Run has failed | `"Run has failed. Start a new fetch first."` |
| **409** | Fetch not started | `"Fetch has not started yet. Call /fetch first."` |
| **409** | Not normalized | `"Run has not been normalized yet. Call /normalize first."` |
| **502** | Snapshot not valid JSON | `"Snapshot at '{key}' is not valid JSON."` |
| **502** | Blob download failure | Dynamic from `RuntimeError` |

### Drive Router (`/api/drive/*`)

| HTTP Status | Condition | Detail Message |
|---|---|---|
| **400** | Missing `folder_id` | `"folder_id is required"` |
| **400** | Drive config error | `"Drive config error: {exc}"` |
| **400** | Missing manifest file_id | `"file_id is required (or configure DRIVE_EVIDENCE_MANIFEST_FILE_ID)."` |
| **401** | Drive 401 | Proxied from `DriveHttpError` body |
| **401** | Missing auth | `"Unauthorized"` |
| **403** | Drive 403 | Proxied from `DriveHttpError` body |
| **404** | Drive 404 | Proxied from `DriveHttpError` body |
| **422** | Manifest parse failed | `"Evidence manifest parse failed: {exc}"` |
| **502** | Drive API error (non-401/403/404) | Proxied from `DriveHttpError` body |
| **502** | Drive file not valid JSON | `"Drive file '{file_id}' did not contain valid JSON."` |

---

## 4. Retry Strategies Summary

| Component | Strategy | Max Retries | Backoff | Jitter |
|---|---|---|---|---|
| **QBO HTTP client** | Exponential backoff | 3 | 0.5s × 2^n | None |
| **QBO token refresh** | None (single attempt) | 0 | — | — |
| **QBO 401 → refresh → retry** | Token refresh once | 1 refresh | No wait | — |
| **Drive HTTP client** | None | 0 | — | — |
| **Drive 401 → refresh → retry** | Token refresh once | 1 refresh | No wait | — |
| **API routers** | None (pass-through) | 0 | — | — |
| **Cosmos writes** | None | 0 | — | — |
| **Blob storage reads** | None | 0 | — | — |

---

## 5. Error Propagation Flow

```
QBO API / Drive API
    ↓ (error)
QBOHttpError / DriveHttpError
    ↓ (caught in API router)
HTTPException(status_code, detail)
    ↓ (FastAPI middleware)
JSON response: { "detail": "..." }
    ↓ (MCP server proxy)
MCP tool returns error payload to agent
    ↓ (agent handles)
Agent reports error to user or replans
```

### Review Run Error Handling

When an error occurs during an async review run:

```python
except Exception as exc:
    record.status = "failed"
    record.completed_at = datetime.now(timezone.utc)
    record.error = str(exc)
    update_balance_sheet_run(record)
```

The error message is stored in `record.error` and surfaced in the run response.

---

## 6. User-Facing Error Messages

These are the messages that reach the frontend or MCP agents:

| Category | Example Message | User Action |
|---|---|---|
| **QBO not connected** | "QBO connection missing for client_id 'xyz'. Did you mean 'blackbird_fabrics'?" | Connect via `/qbo/connect` |
| **QBO expired** | `"token_expired"` (via `/api/qbo/validate`) | Re-authenticate in QBO |
| **Review stuck** | `"Run is still in progress. Wait and retry."` | Poll again later |
| **Review failed** | `"Run has failed. Start a new fetch first."` | Start a new run |
| **Wrong pipeline stage** | `"Run has not been normalized yet. Call /normalize first."` | Call the correct phase endpoint |
| **Drive not configured** | `"Drive config error: Missing required environment variable: DRIVE_CLIENT_ID"` | Set environment variables |
| **Intuit down** | `"QBO report call failed (BalanceSheet): QBO HTTP 503: Service Unavailable"` | Retry later |
| **Access denied** | `"Access denied for the provided storage key."` | Use keys from your own run |

---

## 7. Recommendations

| Gap | Risk | Recommendation |
|---|---|---|
| No jitter in QBO backoff | Thundering herd under load | Add random jitter: `sleep(backoff * (0.5 + random()))` |
| No retry in Drive client | Single transient failure kills operation | Add retry/backoff matching QBO pattern |
| Cosmos write failures silently swallowed | Token refresh succeeds but persistence fails → next restart loses tokens | Log at ERROR level; consider failing the operation |
| No circuit breaker | Repeated failures consume all retries | Add circuit breaker for external APIs |
| Error messages expose internals | Stack traces may leak in `detail` | Sanitize error details in production |
