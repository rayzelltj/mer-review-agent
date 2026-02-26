#!/usr/bin/env bash
set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required." >&2
  exit 1
fi

BACKEND_BASE_URL="${BACKEND_BASE_URL:-}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
AUTH_TOKEN_RESOURCE="${AUTH_TOKEN_RESOURCE:-}"
CLIENT_ID="${CLIENT_ID:-}"
PERIOD_END="${PERIOD_END:-}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-300}"

if [[ -z "$BACKEND_BASE_URL" || -z "$CLIENT_ID" || -z "$PERIOD_END" ]]; then
  cat >&2 <<'EOF'
ERROR: Required env vars are missing.
Set:
  BACKEND_BASE_URL
  CLIENT_ID
  PERIOD_END
Auth (choose one):
  AUTH_TOKEN
  AUTH_TOKEN_RESOURCE (script will call az account get-access-token)
Optional:
  POLL_INTERVAL_SECONDS (default: 5)
  RUN_TIMEOUT_SECONDS (default: 300)
EOF
  exit 1
fi

BACKEND_BASE_URL="${BACKEND_BASE_URL%/}"

if [[ -z "$AUTH_TOKEN" && -n "$AUTH_TOKEN_RESOURCE" ]]; then
  if ! command -v az >/dev/null 2>&1; then
    echo "ERROR: az CLI is required when AUTH_TOKEN_RESOURCE is set." >&2
    exit 1
  fi
  set +e
  TOKEN_OR_ERR="$(az account get-access-token --resource "$AUTH_TOKEN_RESOURCE" --query accessToken -o tsv 2>&1)"
  AZ_EXIT=$?
  set -e
  if [[ $AZ_EXIT -ne 0 || -z "$TOKEN_OR_ERR" ]]; then
    echo "ERROR: failed to obtain access token for resource '$AUTH_TOKEN_RESOURCE'." >&2
    echo "$TOKEN_OR_ERR" >&2
    if echo "$TOKEN_OR_ERR" | grep -q "AADSTS65001"; then
      TENANT_HINT="$(echo "$TOKEN_OR_ERR" | awk -F'--tenant \"' 'NF>1 { split($2, a, "\""); print a[1]; exit }')"
      if [[ -n "$TENANT_HINT" ]]; then
        echo "ACTION: run interactive consent once:" >&2
        echo "  az login --tenant \"$TENANT_HINT\" --scope \"$AUTH_TOKEN_RESOURCE/.default\"" >&2
      fi
    fi
    exit 6
  fi
  AUTH_TOKEN="$TOKEN_OR_ERR"
fi

if [[ -z "$AUTH_TOKEN" ]]; then
  echo "ERROR: AUTH_TOKEN is required (or set AUTH_TOKEN_RESOURCE for az auto-token)." >&2
  exit 1
fi

json_get() {
  local url="$1"
  curl -sS --fail-with-body \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    -H "Accept: application/json" \
    "$url"
}

json_post() {
  local url="$1"
  local body="$2"
  curl -sS --fail-with-body \
    -X POST \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    "$url" \
    -d "$body"
}

echo "==> Checking readiness"
READY_JSON="$(curl -sS --fail-with-body "${BACKEND_BASE_URL}/readyz")"
echo "$READY_JSON" | jq .

echo "==> Checking QBO status for client_id=${CLIENT_ID}"
QBO_STATUS_JSON="$(json_get "${BACKEND_BASE_URL}/api/qbo/status?client_id=${CLIENT_ID}")"
echo "$QBO_STATUS_JSON" | jq .

CONNECTED="$(echo "$QBO_STATUS_JSON" | jq -r '.connected // false')"
if [[ "$CONNECTED" != "true" ]]; then
  echo "ERROR: QBO is not connected for client_id=${CLIENT_ID}" >&2
  exit 2
fi

echo "==> Starting balance sheet review run"
RUN_JSON="$(json_post \
  "${BACKEND_BASE_URL}/api/reviews/balance-sheet/run" \
  "{\"client_id\":\"${CLIENT_ID}\",\"period_end\":\"${PERIOD_END}\"}")"
echo "$RUN_JSON" | jq .

RUN_ID="$(echo "$RUN_JSON" | jq -r '.run_id // empty')"
RUN_STATUS="$(echo "$RUN_JSON" | jq -r '.status // empty')"
if [[ -z "$RUN_ID" || "$RUN_STATUS" != "queued" ]]; then
  echo "ERROR: Invalid run start response." >&2
  exit 3
fi

echo "==> Polling run_id=${RUN_ID} (timeout=${RUN_TIMEOUT_SECONDS}s, interval=${POLL_INTERVAL_SECONDS}s)"
START_TS="$(date +%s)"
while true; do
  RUN_STATE_JSON="$(json_get "${BACKEND_BASE_URL}/api/reviews/balance-sheet/runs/${RUN_ID}")"
  STATUS="$(echo "$RUN_STATE_JSON" | jq -r '.status // empty')"
  NOW_TS="$(date +%s)"
  ELAPSED="$((NOW_TS - START_TS))"

  echo "  [${ELAPSED}s] status=${STATUS}"

  if [[ "$STATUS" == "done" ]]; then
    PERIOD_COL_COUNT="$(echo "$RUN_STATE_JSON" | jq -r '.balance_sheet_view.period_columns | length // 0')"
    TOTALS_JSON="$(echo "$RUN_STATE_JSON" | jq '.totals // {}')"
    echo "==> Run completed"
    echo "run_id=${RUN_ID}"
    echo "status=${STATUS}"
    echo "period_columns=${PERIOD_COL_COUNT}"
    echo "totals=${TOTALS_JSON}"
    exit 0
  fi

  if [[ "$STATUS" == "failed" ]]; then
    echo "ERROR: Run failed." >&2
    echo "$RUN_STATE_JSON" | jq .
    exit 4
  fi

  if (( ELAPSED >= RUN_TIMEOUT_SECONDS )); then
    echo "ERROR: Run polling timed out after ${RUN_TIMEOUT_SECONDS}s." >&2
    echo "$RUN_STATE_JSON" | jq .
    exit 5
  fi

  sleep "$POLL_INTERVAL_SECONDS"
done
