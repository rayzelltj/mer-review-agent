# Google Drive & Sheets Integration — MER Review Agent

> **Status:** Living document
> **Confidence:** Mixed — connector code exists but full integration is MVP2
> **See also:** `docs/architecture/mer-review-agent-spec.md` §4 (MVP2 scope)

---

## Overview

Google Drive integration provides supporting evidence documents (bank statements, loan schedules, working papers, etc.) that complement QBO data in the review process. Google Sheets is planned as the output format for the MER Review Package.

**Current status:**
- ✅ Drive connector code exists in the backend
- ✅ MCP tools for Drive operations exist in FinanceService
- ✅ Evidence manifest adapter exists
- 🔍 Full integration flow is planned for MVP2
- ⚠️ End-to-end Drive-based review with real evidence is not yet production-verified

---

## Backend Connector

Drive connector code is located at:

| File | Purpose |
|---|---|
| `src/backend/connectors/drive/` | Drive client implementation |
| `src/backend/api/drive.py` | REST API endpoints for Drive operations |

### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/drive/status` | GET | Check Drive connection status + folder accessibility |
| `/api/drive/files/list` | POST | List files in a Drive folder (paginated) |
| `/api/drive/files/get` | POST | Download file content + metadata |
| `/api/drive/evidence/manifest` | POST | Fetch & parse evidence manifest JSON |

✅ *Verified line-by-line in code:* `src/backend/api/drive.py`

---

## MCP Finance Tools (Drive-Related)

| MCP Tool | Backend Endpoint | Purpose |
|---|---|---|
| `list_drive_files` | `GET /api/drive/files` | List available evidence files |
| `get_drive_file` | `GET /api/drive/files/{id}` | Retrieve specific file |
| `upload_drive_evidence` | `POST /api/drive/evidence/upload` | Upload supporting evidence |
| `get_evidence_manifest` | `GET /api/drive/evidence/manifest` | Get evidence manifest for a client |

✅ *Verified in code:* `src/mcp_server/services/finance_service.py`

---

## Auth Model

✅ *Verified line-by-line in:* `src/backend/connectors/drive/config.py`, `src/backend/connectors/drive/auth.py`

### Credential Type: OAuth2 Refresh Token (NOT Service Account)

The Drive connector uses **OAuth2 refresh-token credentials** — the same pattern as QBO. This is NOT a Google Service Account; it requires a human to perform initial consent.

### Credential Resolution Chain

`build_drive_config()` resolves credentials in this priority order:

| Priority | Source | When Used |
|---|---|---|
| 1 | **Cosmos DB client record** (`drive` sub-object) | Production with `QBO_CLIENT_STORE=cosmos` |
| 2 | **`config/clients.json`** (`clients.{id}.drive` object) | File-mode / local dev |
| 3 | **Environment variables** | Fallback for all modes |

### Required Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `DRIVE_CLIENT_ID` | ✅ Always | Google OAuth app client ID |
| `DRIVE_CLIENT_SECRET` | ✅ Always | Google OAuth app client secret |
| `DRIVE_REFRESH_TOKEN` | ✅ Unless in client record | Google OAuth refresh token |
| `DRIVE_ACCESS_TOKEN` | Optional | Pre-fetched access token (auto-refreshed if missing/expired) |
| `DRIVE_TOKEN_EXPIRES_AT` | Optional | ISO 8601 or Unix epoch expiry |
| `DRIVE_ROOT_FOLDER_ID` | Optional | Default root folder for file listing |
| `DRIVE_EVIDENCE_MANIFEST_FILE_ID` | Optional | Default evidence manifest file |
| `DRIVE_EVIDENCE_ENABLED` | Optional | `true`/`1`/`yes` to enable evidence rules |

### Per-Client Overrides

When a `client_id` is resolved (via alias or direct match), the connector loads per-client Drive settings:

**Cosmos mode** (`drive` sub-object in the client record):
```json
{
  "id": "blackbird_fabrics",
  "drive": {
    "refresh_token": "1//0...",
    "access_token": "ya29...",
    "token_expires_at": "2025-01-15T12:00:00+00:00",
    "root_folder_id": "1ABC...",
    "evidence_manifest_file_id": "1XYZ...",
    "include_items_from_all_drives": true,
    "supports_all_drives": true
  }
}
```

**File mode** (`config/clients.json`):
```json
{
  "clients": {
    "blackbird": {
      "drive": {
        "root_folder_id": "1ABC...",
        "evidence_manifest_file_id": "1XYZ...",
        "refresh_token": "1//0..."
      }
    }
  }
}
```

### Token Refresh Flow

✅ *Verified in:* `src/backend/connectors/drive/auth.py`

1. **Pre-call check:** `ensure_access_token_valid(config)` runs before each Drive API call
2. **Expiry buffer:** Tokens are considered expired **30 seconds before** actual expiry (defensive)
3. **Refresh POST** to `https://oauth2.googleapis.com/token`:
   - Body: `grant_type=refresh_token&client_id=...&client_secret=...&refresh_token=...`
   - Content-Type: `application/x-www-form-urlencoded`
   - Timeout: 30 seconds
4. **Token persistence after refresh:**
   - Updates `os.environ` (`DRIVE_ACCESS_TOKEN`, `DRIVE_REFRESH_TOKEN`, `DRIVE_TOKEN_EXPIRES_AT`)
   - If Cosmos mode + `client_record_id` present → upserts updated `drive` sub-object in client record
5. **Reactive 401 refresh:** If a Drive API call returns 401, `_drive_get_bytes()` refreshes the token once and retries

### Drive Client HTTP Behavior

✅ *Verified in:* `src/backend/connectors/drive/client.py`

| Behavior | Detail |
|---|---|
| **Base URL** | `https://www.googleapis.com/drive/v3` |
| **Auth** | `Bearer` token in `Authorization` header |
| **Timeout** | 30 seconds per request |
| **401 handling** | Refresh token once, retry; raise `DriveHttpError` on second failure |
| **No retry/backoff** | Unlike QBO, Drive client does NOT retry on 429/5xx — errors raise immediately |
| **Google Docs export** | Detects `application/vnd.google-apps.*` MIME types and auto-exports (spreadsheet→CSV, document→text/plain) |
| **Pagination** | `list_files()` handles `nextPageToken` pagination automatically |

---

## Operational Setup — How to Configure Drive for a New Client

### Step 1: Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an **OAuth 2.0 Client ID** (type: Web application)
3. Add authorized redirect URIs for your backend
4. Note the `Client ID` and `Client Secret`
5. Set environment variables:
   ```bash
   DRIVE_CLIENT_ID=<your-client-id>
   DRIVE_CLIENT_SECRET=<your-client-secret>
   ```

### Step 2: Obtain Initial Refresh Token

1. Use the OAuth Playground or a custom consent flow to get a refresh token
2. Required scope: `https://www.googleapis.com/auth/drive.readonly` (minimum)
3. Store the refresh token in the appropriate location:
   - **Cosmos mode:** Add to the client record's `drive.refresh_token` field
   - **File mode:** Add to `config/clients.json` under the client's `drive` section
   - **Env var fallback:** Set `DRIVE_REFRESH_TOKEN=<token>`

### Step 3: Configure Client-Level Settings

Add Drive settings to the client record (Cosmos or `clients.json`):

```json
{
  "drive": {
    "refresh_token": "1//0...",
    "root_folder_id": "<shared-folder-id>",
    "evidence_manifest_file_id": "<manifest-file-id>"
  }
}
```

### Step 4: Enable Drive Evidence

```bash
DRIVE_EVIDENCE_ENABLED=true
```

Without this flag, Drive-only rules (`BS-INVESTMENT-BALANCE-MATCH`, `BS-LOAN-BALANCE-MATCH`, `BS-PETTY-CASH-MATCH`, `BS-WORKING-PAPER-RECONCILES`) are automatically disabled.

### Step 5: Verify Connection

```bash
curl -sS -H "Authorization: Bearer $TOKEN" \
  "https://<backend>/api/drive/status?client_id=<client_id>" | jq .
```

Expected: `connected: true`, `folder_accessible: true`

---

## Evidence Flow

```
Google Drive (client folder)
    ├── Evidence manifest file (JSON/Sheet)
    │       Lists all supporting documents per evidence type
    ├── Bank statements (PDF/CSV)
    ├── Loan schedules (Sheet/PDF)
    ├── Investment statements (PDF)
    ├── Petty cash documentation (PDF/image)
    └── Working papers (CSV/Sheet)

    ↓ (Drive connector fetches via download_file_bytes)

Evidence Manifest Adapter
    → src/backend/adapters/mock_evidence/evidence_manifest.py
    → evidence_bundle_from_manifest(manifest) → EvidenceBundle

    ↓ (used in RuleContext)

Rules Engine
    → Rules that require Drive evidence:
       - BS-INVESTMENT-BALANCE-MATCH
       - BS-LOAN-BALANCE-MATCH
       - BS-PETTY-CASH-MATCH
       - BS-WORKING-PAPER-RECONCILES
```

These rules auto-disable when no Drive manifest is configured:

```python
DRIVE_ONLY_RULE_IDS = {
    "BS-INVESTMENT-BALANCE-MATCH",
    "BS-LOAN-BALANCE-MATCH",
    "BS-PETTY-CASH-MATCH",
    "BS-WORKING-PAPER-RECONCILES",
}
```

✅ *Verified in code:* `src/backend/api/reviews.py`

---

## Folder/File Permissions Model

✅ *Verified from code:* The connector uses OAuth2 user-delegated tokens (not a service account), so access is scoped to whatever the authorizing user granted.

| Principle | Implementation |
|---|---|
| OAuth2 user-delegated access | Refresh token obtained during initial consent defines the scope |
| Shared Drive support | `supports_all_drives=true` and `include_items_from_all_drives=true` (defaults) |
| Users don't directly access Drive | Backend acts as intermediary; users interact via the web UI |
| Evidence files are read for review | Download uses `alt=media` for binary or `/export` for Google Docs formats |

---

## MER Review Package Export (MVP2)

**Planned capability:** Export review results to a formatted Google Sheet that serves as the MER Review Package.

| Aspect | Status |
|---|---|
| Sheet creation | ⚠️ Not yet implemented |
| Sheet formatting | ⚠️ Not yet implemented |
| Evidence linking in Sheet | ⚠️ Not yet implemented |
| Sharing / permissions | ⚠️ Not yet implemented |

---

## Known Gaps

| Gap | Impact | Priority |
|---|---|---|
| Real bank statement parsing (PDF/CSV) | Evidence rules fall back to NEEDS_REVIEW | High (MVP2) |
| Petty cash document parsing | Petty cash match rule uses mock data | High (MVP2) |
| Loan schedule / investment statement parsing | Evidence match rules use mock data | High (MVP2) |
| MER Review Package Google Sheet export | No shareable output package | Medium (MVP2) |
| Drive folder permission auditing | Can't verify least-privilege access | Medium |
| File versioning / change detection | May re-process unchanged files | Low |
