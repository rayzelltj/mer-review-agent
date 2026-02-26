# MER MVP1 Smoke Checklist (QBO -> Review Run)

This checklist is the canonical manual smoke path for MVP1:
- login/session
- QBO connect callback
- connected-state refresh
- company selection + review run
- result rendering contract

Scope:
- QBO connector only
- balance sheet review flow only

## 1) Required Inputs

Set the following before running API smoke commands:

```bash
export BACKEND_BASE_URL="https://<your-backend-host>"
export AUTH_TOKEN="<aad-access-token>"
export CLIENT_ID="<canonical-client-id>"
export PERIOD_END="2025-12-31"
```

Alternative auth mode (script auto-fetches token via az CLI):

```bash
export AUTH_TOKEN_RESOURCE="api://<allowed-audience-app-id>"
```

Notes:
- `BACKEND_BASE_URL` must not end with `/`.
- auth options:
  - `AUTH_TOKEN` must be valid for backend APIs, or
  - `AUTH_TOKEN_RESOURCE` must be consented for Azure CLI token acquisition.
- `CLIENT_ID` should match the connected client record.
- `PERIOD_END` is `YYYY-MM-DD`.

## 2) Browser Flow Smoke (Login + QBO Callback)

1. Open the frontend web app and sign in.
2. Navigate to QBO connect for target client:
   - `/qbo/connect?client_id=<CLIENT_ID>`
3. Complete Intuit OAuth consent.
4. Confirm callback page resolves through frontend and backend:
   - frontend route: `/qbo/callback?...`
   - backend API call: `/api/qbo/callback?...`
5. Confirm frontend returns to home with connected marker:
   - `/?qbo_connected=1&client_id=<CLIENT_ID>`

Expected result:
- UI stores selected `client_id`.
- QBO status banner clears for that client.

## 3) API Contract Smoke (Connected State + Run Lifecycle)

### 3.1 QBO connected-state check

```bash
curl -sS \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  "$BACKEND_BASE_URL/api/qbo/status?client_id=$CLIENT_ID" | jq .
```

Expected:
- `connected=true`
- `client_id=<CLIENT_ID>`
- `realm_id` present

### 3.2 Start review run

```bash
curl -sS -X POST \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "$BACKEND_BASE_URL/api/reviews/balance-sheet/run" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"period_end\":\"$PERIOD_END\"}" | jq .
```

Expected:
- `status=queued`
- `run_id` present

### 3.3 Poll run status to terminal

```bash
RUN_ID="<run_id_from_previous_step>"
curl -sS \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  "$BACKEND_BASE_URL/api/reviews/balance-sheet/runs/$RUN_ID" | jq .
```

Poll until `status` is `done` or `failed`.

Expected on success:
- `status=done`
- `run_id=<RUN_ID>`
- `balance_sheet_view.period_columns` includes current and prior periods
- `totals` present

## 4) Optional: One-Command API Smoke

Use the helper script:

```bash
scripts/smoke/mer_mvp1_api_smoke.sh
```

Inputs consumed by script:
- `BACKEND_BASE_URL`
- `AUTH_TOKEN` or `AUTH_TOKEN_RESOURCE`
- `CLIENT_ID`
- `PERIOD_END`

## 5) Fail-Fast Interpretation

- `401 Unauthorized`:
  - invalid/expired token or session mismatch
- token fetch fails with `AADSTS65001`:
  - tenant consent missing for Azure CLI on requested API audience
  - run interactive consent once:
    - `az login --tenant "<tenant-id>" --scope "<resource>/.default"`
  - script exits with code `6`
- `409` from `/api/reviews/balance-sheet/run`:
  - QBO not connected for `client_id`
- `400 Invalid or expired state` from callback:
  - OAuth state mismatch/expiry; restart connect flow
- `503` during callback:
  - token/state persistence failure; check backend/Cosmos availability

## 6) Evidence to Capture Per Smoke Run

- UTC timestamp
- `client_id`
- `period_end`
- `run_id`
- terminal run status
- `x-trace-id` header values from failed requests (if any)
