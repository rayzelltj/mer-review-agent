# API Reference — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified line-by-line from router source code
> **Source files:** `src/backend/api/qbo.py`, `src/backend/api/qbo_data.py`, `src/backend/api/reviews.py`, `src/backend/api/drive.py`, `src/backend/app.py`

---

## Router Mount Points

All routers are mounted in `src/backend/app.py`:

| Router | Prefix | Tags | Source File |
|---|---|---|---|
| `qbo_router` | `/qbo` | `qbo` | `api/qbo.py` |
| `qbo_api_router` | `/api/qbo` | `qbo` | `api/qbo.py` |
| `qbo_data_router` | `/api/qbo/data` | `qbo-data` | `api/qbo_data.py` |
| `reviews_router` | `/api/reviews` | `reviews` | `api/reviews.py` |
| `drive_router` | `/api/drive` | `drive` | `api/drive.py` |
| `app_v4` | `/api/v4` | v4 | `v4/api/router.py` |

**Authentication:** All MER endpoints require an authenticated user via Azure EasyAuth or bearer token. The user principal ID is extracted from request headers.

---

## 1. QBO OAuth Endpoints (`/qbo/*` + `/api/qbo/*`)

### `GET /qbo/oauth/start`

Start the QBO OAuth2 flow (redirect to Intuit).

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `target` | query | `string` | No | `"dev"` to use dev redirect URI |
| `client_id` | query | `string` | No | Client identifier to bind the connection |

**Response:** `302 Redirect` to Intuit OAuth2 authorization URL.

---

### `GET /api/qbo/connect/start`

Same as `/qbo/oauth/start` but on the `/api` prefix.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `client_id` | query | `string` | **Yes** | Client identifier |
| `target` | query | `string` | No | `"dev"` for dev redirect URI |

**Response:** `302 Redirect` to Intuit OAuth2 authorization URL.

---

### `GET /api/qbo/connect/prepare`

Prepare OAuth URL without redirecting (frontend fetches URL, opens popup).

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `client_id` | query | `string` | **Yes** | Client identifier |
| `target` | query | `string` | No | `"dev"` for dev redirect URI |

**Response:**
```json
{
  "authorization_url": "https://appcenter.intuit.com/connect/oauth2?...",
  "client_id": "blackbird_fabrics"
}
```

---

### `GET /qbo/callback` / `GET /api/qbo/callback`

OAuth2 callback from Intuit after user consent.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `code` | query | `string` | **Yes** | Authorization code from Intuit |
| `realmId` | query | `string` | **Yes** | QBO company realm ID |
| `state` | query | `string` | **Yes** | CSRF state token |
| `client_id` | query | `string` | No | Client identifier override |

**Response (200):**
```json
{
  "status": "ok",
  "connected": true,
  "store_mode": "cosmos",
  "client_id": "blackbird_fabrics",
  "realm_id": "193514892490929",
  "token_expires_at": "2025-01-15T13:00:00+00:00"
}
```

**Error responses:** `400` (invalid/expired state), `403` (user mismatch), `502` (token exchange failed), `503` (persistence failed).

---

### `GET /api/qbo/status`

Check QBO connection status for a client.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `client_id` | query | `string` | No | Client identifier |

**Response (200):**
```json
{
  "connected": true,
  "store_mode": "cosmos",
  "client_id": "blackbird_fabrics",
  "requested_client_id": "blackbird",
  "resolved_client_id": "blackbird_fabrics",
  "realm_id": "193514892490929"
}
```

When not connected:
```json
{
  "connected": false,
  "reason": "no record found",
  "store_mode": "cosmos",
  "client_id": "unknown_client",
  "suggested_client_ids": ["blackbird_fabrics"]
}
```

---

### `GET /api/qbo/validate`

Deep validation — checks connection AND performs live Intuit API probe.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `client_id` | query | `string` | No | Client identifier |

**Response (200):**
```json
{
  "connected": true,
  "live": true,
  "store_mode": "cosmos",
  "client_id": "blackbird_fabrics",
  "realm_id": "193514892490929"
}
```

When token expired:
```json
{
  "connected": true,
  "live": false,
  "reason": "token_expired",
  "detail": "QBO HTTP 401: Unauthorized"
}
```

---

### `GET /api/qbo/debug/clients`

List all connected QBO clients. **Requires `QBO_DEBUG_ENDPOINTS_ENABLED=true`.**

**Response (200):**
```json
{
  "store_mode": "cosmos",
  "clients": [
    {
      "client_id": "blackbird_fabrics",
      "realm_id": "193514892490929",
      "connected": true,
      "has_refresh_token": true
    }
  ]
}
```

**Response (404):** Debug endpoints disabled.

---

## 2. QBO Data Endpoints (`/api/qbo/data/*`)

All QBO data endpoints follow a common pattern:
- **Method:** POST (request body contains parameters)
- **Auth:** Bearer token required
- **Client resolution:** `client_id` is resolved via aliases → Cosmos/file lookup → QBO config
- **Error on QBO failure:** `502` with QBO error details

### Common Response Envelope

All data endpoints wrap responses in:
```json
{
  "tool": "<tool_name>",
  "client_id": "<resolved_client_id>",
  "store_mode": "cosmos|file",
  "realm_id": "<qbo_realm_id>",
  "params": { ... },
  "report": { ... }
}
```

---

### `POST /api/qbo/data/balance-sheet`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `as_of_date` | `date` | **Yes** | — | Balance sheet date |
| `basis` | `string` | No | `"Accrual"` | `"Accrual"` or `"Cash"` |
| `summarize_by` | `string` | No | — | Column grouping |
| `filters` | `object` | No | — | QBO dimension filters |

---

### `POST /api/qbo/data/profit-and-loss`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `start_date` | `date` | **Yes** | — | Period start |
| `end_date` | `date` | **Yes** | — | Period end |
| `basis` | `string` | No | `"Accrual"` | Accounting basis |
| `summarize_by` | `string` | No | — | Column grouping |
| `filters` | `object` | No | — | Dimension filters |

---

### `POST /api/qbo/data/trial-balance`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `start_date` | `date` | **Yes** | — | Period start |
| `end_date` | `date` | **Yes** | — | Period end |
| `basis` | `string` | No | `"Accrual"` | Accounting basis |
| `filters` | `object` | No | — | Dimension filters |

---

### `POST /api/qbo/data/cash-flow`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `start_date` | `date` | **Yes** | — | Period start |
| `end_date` | `date` | **Yes** | — | Period end |
| `basis` | `string` | No | `"Accrual"` | Accounting basis |
| `filters` | `object` | No | — | Dimension filters |

---

### `POST /api/qbo/data/gl-detail`

General Ledger detail report with optional amount filtering.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `start_date` | `date` | **Yes** | — | Period start |
| `end_date` | `date` | **Yes** | — | Period end |
| `basis` | `string` | No | `"Accrual"` | Accounting basis |
| `account_id` | `string` | No | — | Filter by account ID |
| `account_name` | `string` | No | — | Filter by account name |
| `class_name` | `string` | No | — | Filter by class |
| `location` | `string` | No | — | Filter by location/department |
| `customer` | `string` | No | — | Filter by customer/project |
| `vendor` | `string` | No | — | Filter by vendor |
| `min_amount` | `float` | No | — | Filter rows below this amount |

---

### `POST /api/qbo/data/transactions/by-account`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `account_id` | `string` | **Yes** | — | Account to query |
| `start_date` | `date` | **Yes** | — | Period start |
| `end_date` | `date` | **Yes** | — | Period end |
| `basis` | `string` | No | `"Accrual"` | Accounting basis |
| `include_splits` | `bool` | No | `true` | Include split detail |
| `filters` | `object` | No | — | Dimension filters |

**Fallback:** If `TransactionListByAccount` returns 502, falls back to `TransactionList`.

---

### `POST /api/qbo/data/transaction`

Fetch a single transaction by ID (searches across entity types).

| Field | Type | Required | Description |
|---|---|---|---|
| `transaction_id` | `string` | **Yes** | QBO transaction ID |
| `client_id` | `string` | No | Client identifier |

**Response (200):**
```json
{
  "tool": "qbo_get_transaction",
  "transaction_id": "123",
  "entity_type": "Invoice",
  "transaction": { ... }
}
```

**Entity search order:** Invoice, Bill, JournalEntry, SalesReceipt, Payment, BillPayment, CreditMemo, VendorCredit, Check, Deposit, Transfer, Purchase, RefundReceipt.

---

### `POST /api/qbo/data/accounts`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `include_inactive` | `bool` | No | `true` | Include inactive accounts |

---

### `POST /api/qbo/data/ar-aging`

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | No | Client identifier |
| `as_of_date` | `date` | **Yes** | Aging date |

**Response:** `{ summary: {...}, detail: {...} }`

---

### `POST /api/qbo/data/ap-aging`

Same schema as AR aging.

---

### `POST /api/qbo/data/open-invoices`

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | No | Client identifier |
| `start_date` | `date` | No | Filter start |
| `end_date` | `date` | No | Filter end |

---

### `POST /api/qbo/data/open-bills`

Same schema as open invoices.

---

### `POST /api/qbo/data/bank-reconciliation-status`

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | No | Client identifier |
| `bank_account_id` | `string` | **Yes** | QBO account ID |
| `as_of_date` | `date` | No | Check date |

**Response (200):**
```json
{
  "tool": "qbo_get_bank_reconciliation_status",
  "bank_account_id": "42",
  "status": "reconciled_through_as_of",
  "last_reconciliation_date": "2025-01-31",
  "supported": true
}
```

---

### `POST /api/qbo/data/sales-tax-returns`

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | No | Client identifier |
| `start_date` | `date` | No | Filter start |
| `end_date` | `date` | No | Filter end |

**Response:** `{ agencies: [...], returns: [...], payments: [...] }`

---

### `POST /api/qbo/data/sales-tax-liability`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | auto | Client identifier |
| `start_date` | `date` | **Yes** | — | Period start |
| `end_date` | `date` | **Yes** | — | Period end |
| `basis` | `string` | No | `"Accrual"` | Accounting basis |

**Fallback:** If `TaxSummary` report unavailable, aggregates from `tax_returns`.

---

### `POST /api/qbo/data/payroll-liabilities`

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | No | Client identifier |
| `as_of_date` | `date` | No | Reference date |

Returns payroll-related liability accounts (matched by name heuristic: "payroll", "wages payable", "salary payable", "source deduction", "cpp payable", "ei payable", "income tax payable", "withholding").

---

## 3. Review Endpoints (`/api/reviews/*`)

### `POST /api/reviews/balance-sheet/run`

Start a full balance-sheet review (fetch + normalize + rules — monolith pipeline).

**Request body:**
```json
{
  "client_id": "blackbird_fabrics",
  "period_end": "2025-01-31",
  "notes": "Monthly review"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | **Yes** (min 1 char) | Client identifier |
| `period_end` | `date` | **Yes** | Balance sheet date |
| `notes` | `string` | No | Operator notes |

**Response (200):**
```json
{
  "run_id": "a1b2c3d4...",
  "status": "queued"
}
```

**Errors:** `409` (QBO not connected for client).

**Async:** Run executes in background via `asyncio.create_task()`.

---

### `POST /api/reviews/balance-sheet/fetch`

Start raw QBO fetch only (no normalization, no rules). Sets status to `raw`.

Same request schema as `/balance-sheet/run`.

**Response (200):** `{ "run_id": "...", "status": "queued" }`

---

### `POST /api/reviews/balance-sheet/{run_id}/normalize`

Run normalization on a raw-fetched run. Requires `status=raw`. Sets status to `fetched`.

**Idempotent:** Returns immediately if already `fetched` or `done`.

**Response (200):** Full run record (see GET runs/{run_id}).

**Errors:** `404` (not found), `409` (wrong status).

---

### `POST /api/reviews/balance-sheet/{run_id}/run-rules`

Run rules engine on a normalized run. Requires `status=fetched`. Sets status to `done`.

**Request body:**
```json
{
  "rule_ids": ["BS-TOTAL-ASSETS", "BS-RETAINED-EARNINGS"]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `rule_ids` | `string[]` | No | Subset of rules to run; `null` = all rules |

**Idempotent:** Returns existing findings if already `done`.

**Response (200):** Full run record with findings.

---

### `GET /api/reviews/balance-sheet/runs/{run_id}`

Get a balance sheet review run by ID.

**Response (200):**
```json
{
  "run_id": "a1b2c3d4",
  "session_id": "...",
  "client_id": "blackbird_fabrics",
  "period_end": "2025-01-31",
  "status": "done",
  "created_at": "2025-01-15T12:00:00Z",
  "started_at": "2025-01-15T12:00:01Z",
  "completed_at": "2025-01-15T12:00:15Z",
  "findings": [ { "rule_id": "BS-TOTAL-ASSETS", "status": "pass", ... } ],
  "totals": { "pass": 18, "fail": 2, "needs_review": 4, "not_applicable": 2 },
  "run_report": { ... },
  "balance_sheet_view": { "period_columns": [...], "rows": [...] },
  "summary": "## Balance Sheet Review Summary\n...",
  "hitl_requests": [ ... ],
  "snapshot_keys": { "qbo_balance_sheet": "snapshots/..." },
  "artifact_keys": { "findings": "runs/...", "summary": "runs/..." },
  "error": null
}
```

**Status lifecycle:** `queued` → `running` → `raw` → `fetched` → `done` (or `failed` at any point).

---

### `GET /api/reviews/balance-sheet/find`

Find the latest non-failed run for a (client_id, period_end) pair.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `client_id` | query | `string` | **Yes** | Client identifier |
| `period_end` | query | `date` | **Yes** | Balance sheet date |

**Response (200):** Full run record. **Response (404):** No active run found.

---

### `GET /api/reviews/balance-sheet/runs/{run_id}/snapshots`

List snapshot and artifact keys for a run.

**Response (200):**
```json
{
  "run_id": "a1b2c3d4",
  "client_id": "blackbird_fabrics",
  "period_end": "2025-01-31",
  "status": "done",
  "snapshot_count": 11,
  "artifact_count": 5,
  "snapshot_keys": { "qbo_balance_sheet": "snapshots/blackbird_fabrics/2025-01-31/a1b2c3d4/qbo_balance_sheet.json" },
  "artifact_keys": { "findings": "runs/blackbird_fabrics/2025-01-31/a1b2c3d4/findings.json" }
}
```

---

### `GET /api/reviews/snapshots/content`

Read raw snapshot content.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `snapshot_key` | query | `string` | **Yes** | Key from `snapshot_keys` (must start with `snapshots/`) |

**Response (200):** `{ "snapshot_key": "...", "content_type": "application/json", "source": "blob", "size_bytes": 12345, "snapshot": { ... } }`

**Auth:** Verifies the key belongs to a run owned by the authenticated user.

---

### `GET /api/reviews/artifacts/content`

Read run artifact content.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `artifact_key` | query | `string` | **Yes** | Key from `artifact_keys` (must start with `runs/`) |

**Response (200):** Content decoded as JSON, text, or base64 depending on file type.

---

### `GET /api/reviews/rules`

List all registered balance sheet rules.

**Response (200):**
```json
{
  "rules": [
    {
      "rule_id": "BS-TOTAL-ASSETS",
      "title": "Total Assets = Total Liabilities + Equity",
      "best_practices_reference": "",
      "sources": ["balance_sheet"]
    }
  ],
  "count": 26
}
```

---

### `POST /api/reviews/balance-sheet/{run_id}/evidence`

Submit a human-in-the-loop evidence request.

**Request body:**
```json
{
  "rule_id": "BS-BANK-RECONCILIATION",
  "evidence_type": "bank_statement",
  "description": "Need January bank statement for reconciliation",
  "suggested_source": "Drive"
}
```

**Response (200):**
```json
{
  "run_id": "a1b2c3d4",
  "evidence_submitted": true,
  "evidence_type": "bank_statement",
  "rule_id": "BS-BANK-RECONCILIATION"
}
```

**Dedup:** Duplicate (rule_id, evidence_type) pairs are silently ignored.

---

## 4. Drive Endpoints (`/api/drive/*`)

### `GET /api/drive/status`

Check Drive connection status and folder accessibility.

| Parameter | In | Type | Required | Description |
|---|---|---|---|---|
| `client_id` | query | `string` | No | Client identifier |

**Response (200):**
```json
{
  "connected": true,
  "reason": null,
  "client_id": "blackbird_fabrics",
  "root_folder_id": "1ABC...",
  "evidence_manifest_file_id": "1XYZ...",
  "folder_accessible": true,
  "supports_all_drives": true,
  "include_items_from_all_drives": true
}
```

---

### `POST /api/drive/files/list`

List files in a Drive folder.

**Request body:**
```json
{
  "client_id": "blackbird_fabrics",
  "folder_id": "1ABC...",
  "query": "mimeType='application/pdf'",
  "page_size": 100
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | — | Client identifier |
| `folder_id` | `string` | No | config default | Drive folder ID |
| `query` | `string` | No | — | Additional Drive query filter |
| `page_size` | `int` | No | `100` | Results per page (1–1000) |

**Response (200):**
```json
{
  "client_id": "blackbird_fabrics",
  "folder_id": "1ABC...",
  "count": 5,
  "files": [
    { "id": "...", "name": "bank_statement_jan.pdf", "mimeType": "application/pdf", "modifiedTime": "...", "size": "12345" }
  ]
}
```

---

### `POST /api/drive/files/get`

Download file content + metadata.

**Request body:**
```json
{
  "client_id": "blackbird_fabrics",
  "file_id": "1FILE...",
  "export_mime_type": "text/csv",
  "max_inline_bytes": 300000
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `client_id` | `string` | No | — | Client identifier |
| `file_id` | `string` | **Yes** | — | Drive file ID |
| `export_mime_type` | `string` | No | auto | Export format for Google Docs |
| `max_inline_bytes` | `int` | No | `300000` | Max bytes to inline (1024–2M) |

**Response (200):** Includes `content_text` (text), `content_json` (JSON), or `content_base64` (binary).

When file exceeds `max_inline_bytes`: `{ "content_omitted": true, "max_inline_bytes": 300000 }`.

---

### `POST /api/drive/evidence/manifest`

Fetch and parse the evidence manifest from Drive.

**Request body:**
```json
{
  "client_id": "blackbird_fabrics",
  "file_id": "1MANIFEST..."
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `string` | No | Client identifier |
| `file_id` | `string` | No | Manifest file ID (defaults to config) |

**Response (200):**
```json
{
  "client_id": "blackbird_fabrics",
  "file_id": "1MANIFEST...",
  "evidence_count": 8,
  "evidence_types": ["bank_statement", "investment_statement", "loan_schedule"],
  "manifest": { ... },
  "evidence_items": [ { "evidence_type": "bank_statement", ... } ]
}
```

**Errors:** `400` (no file_id configured), `422` (manifest parse failed), `502` (Drive download failed).

---

## 5. System Endpoints

### `GET /health`

Health check (via `HealthCheckMiddleware`).

### `GET /readyz`

Readiness probe.

**Response (200):** `{ "status": "ready" }`

### `POST /api/user_browser_language`

Set user browser language preference.

**Request body:** `{ "language": "en-US" }`

---

## Pydantic Request Models Summary

| Model | Router | Fields |
|---|---|---|
| `BalanceSheetRunRequest` | reviews | `client_id`, `period_end`, `notes?` |
| `BalanceSheetFetchRequest` | reviews | `client_id`, `period_end`, `notes?` |
| `RunRulesRequest` | reviews | `rule_ids?` |
| `SubmitEvidenceRequest` | reviews | `rule_id`, `evidence_type`, `description`, `suggested_source` |
| `StatementRequest` | qbo-data | `client_id?`, `basis`, `summarize_by?`, `filters?` |
| `DateRangeStatementRequest` | qbo-data | extends StatementRequest + `start_date`, `end_date` |
| `AsOfStatementRequest` | qbo-data | extends StatementRequest + `as_of_date` |
| `GLDetailRequest` | qbo-data | extends DateRangeStatementRequest + `account_id?`, `account_name?`, `class_name?`, `location?`, `customer?`, `vendor?`, `min_amount?` |
| `TransactionsByAccountRequest` | qbo-data | `client_id?`, `account_id`, `start_date`, `end_date`, `basis`, `include_splits`, `filters?` |
| `TransactionRequest` | qbo-data | `transaction_id`, `client_id?` |
| `ListAccountsRequest` | qbo-data | `client_id?`, `include_inactive` |
| `AgingRequest` | qbo-data | `client_id?`, `as_of_date` |
| `OpenDocumentsRequest` | qbo-data | `client_id?`, `start_date?`, `end_date?` |
| `BankReconciliationStatusRequest` | qbo-data | `client_id?`, `bank_account_id`, `as_of_date?` |
| `SalesTaxLiabilityRequest` | qbo-data | `client_id?`, `start_date`, `end_date`, `basis` |
| `SalesTaxReturnsRequest` | qbo-data | `client_id?`, `start_date?`, `end_date?` |
| `PayrollLiabilitiesRequest` | qbo-data | `client_id?`, `as_of_date?` |
| `DriveListFilesRequest` | drive | `client_id?`, `folder_id?`, `query?`, `page_size` |
| `DriveGetFileRequest` | drive | `client_id?`, `file_id`, `export_mime_type?`, `max_inline_bytes` |
| `DriveEvidenceManifestRequest` | drive | `client_id?`, `file_id?` |

---

## Response Model: `BalanceSheetRunRecord`

The review run record returned by all `/api/reviews/balance-sheet/runs/*` endpoints:

| Field | Type | Description |
|---|---|---|
| `run_id` | `string` | Unique run identifier (UUID hex) |
| `session_id` | `string` | Cosmos partition key |
| `client_id` | `string` | Resolved client identifier |
| `period_end` | `date` | Balance sheet date |
| `status` | `enum` | `queued` \| `running` \| `raw` \| `fetched` \| `done` \| `failed` |
| `created_at` | `datetime` | When the run was created |
| `started_at` | `datetime?` | When processing began |
| `completed_at` | `datetime?` | When processing finished |
| `notes` | `string?` | Operator notes |
| `findings` | `RuleResult[]` | Array of rule evaluation results |
| `totals` | `dict[string, int]` | Count by status (pass, fail, needs_review, etc.) |
| `run_report` | `dict?` | Full `RuleRunReport` as JSON |
| `balance_sheet_view` | `dict?` | Rendered balance sheet with period columns |
| `summary` | `string?` | Markdown narrative summary |
| `hitl_requests` | `MissingEvidenceRequest[]` | Human-in-the-loop evidence requests |
| `snapshot_keys` | `dict[string, string]` | Map of snapshot names to storage keys |
| `artifact_keys` | `dict[string, string]` | Map of artifact names to storage keys |
| `error` | `string?` | Error message if `status=failed` |
