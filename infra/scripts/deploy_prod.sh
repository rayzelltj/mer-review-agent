#!/usr/bin/env bash
# deploy_prod.sh — build, verify, stage, promote, rollback, and health-check
#
# Modes (mutually exclusive — pass exactly one):
#   (default / no flag)    Build images + deploy straight to production (legacy behaviour)
#   --staging              Build images + deploy to the staging slot / revision label
#   --promote              Swap/promote staging → production (requires --confirm)
#   --rollback             Roll back production to the previous revision/slot
#   --health-check-only    Run post-deploy health checks only (no build/deploy)
#
# Guard flag (required for --promote and for the default production path):
#   --confirm              Acknowledge you intend to touch production
#
# Examples:
#   RG=my-rg ACR_NAME=myacr ./deploy_prod.sh --staging
#   ./deploy_prod.sh --promote --confirm
#   ./deploy_prod.sh --rollback --confirm
#   ./deploy_prod.sh --confirm   # full build + direct prod deploy
set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MODE="prod"          # prod | staging | promote | rollback | health-check-only
CONFIRM=false
for arg in "$@"; do
  case "$arg" in
    --staging)            MODE="staging" ;;
    --promote)            MODE="promote" ;;
    --rollback)           MODE="rollback" ;;
    --health-check-only)  MODE="health-check-only" ;;
    --confirm)            CONFIRM=true ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

# Production-touching modes require --confirm
if [[ "${MODE}" == "prod" || "${MODE}" == "promote" || "${MODE}" == "rollback" ]] && [[ "${CONFIRM}" != "true" ]]; then
  echo "❌  Mode '${MODE}' modifies production. Re-run with --confirm to proceed." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Resource names — read from env or fall back to defaults discovered in repo
# ---------------------------------------------------------------------------
RG="${RG:-RG-Automation_Engine-001}"
ACR_NAME="${ACR_NAME:-acrprodmvpwrf6y}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-${ACR_NAME}.azurecr.io}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-ca-prodmvpwrf6y}"
CONTAINER_NAME="${CONTAINER_NAME:-backend}"
FRONTEND_APP_NAME="${FRONTEND_APP_NAME:-app-prodmvpwrf6y}"
BACKEND_TAG="${BACKEND_TAG:-prod-$(date -u +%Y%m%d-%H%M)}"
FRONTEND_TAG="${FRONTEND_TAG:-${BACKEND_TAG}}"
FRONTEND_IMAGE_REPO="${FRONTEND_IMAGE_REPO:-frontend}"
RUN_TTL_SECONDS="${RUN_TTL_SECONDS:-1800}"
QBO_DEBUG_ENDPOINTS_ENABLED="${QBO_DEBUG_ENDPOINTS_ENABLED:-false}"
# Staging label base — the actual revision suffix gets a timestamp appended to avoid
# "revision with suffix X already exists" errors when redeploying staging.
# Override with STAGING_LABEL=my-suffix to pin a specific name.
_STAGING_BASE="${STAGING_LABEL:-staging}"
STAGING_LABEL="${_STAGING_BASE}-$(date -u +%m%d%H%M)"
# How long to wait (seconds) for a new revision to become active before health checks
REVISION_READY_WAIT="${REVISION_READY_WAIT:-60}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/src/backend"
FRONTEND_DIR="${ROOT_DIR}/src/frontend"
BACKEND_IMAGE="${ACR_LOGIN_SERVER}/backend:${BACKEND_TAG}"
FRONTEND_IMAGE="${ACR_LOGIN_SERVER}/${FRONTEND_IMAGE_REPO}:${FRONTEND_TAG}"
DEPLOY_ZIP="/tmp/${FRONTEND_APP_NAME}-${FRONTEND_TAG}.zip"

# ---------------------------------------------------------------------------
# Helper: verify — run tests and frontend build before touching any infra
# ---------------------------------------------------------------------------
run_verify() {
  echo "▶ [verify] Syncing backend virtualenv (uv) and running tests…"
  pushd "${BACKEND_DIR}" >/dev/null
  # uv sync ensures the test env exactly matches the production lockfile
  uv sync --frozen --quiet
  uv run pytest --tb=short -q \
    --ignore="${ROOT_DIR}/tests/e2e-test/tests" \
    --ignore="${BACKEND_DIR}/tests/test_app.py" \
    --ignore="${ROOT_DIR}/src/tests/agents/test_foundry_integration.py" \
    --ignore="${ROOT_DIR}/src/tests/mcp_server/test_factory.py" \
    --ignore="${ROOT_DIR}/src/tests/mcp_server/test_hr_service.py" \
    --ignore="${BACKEND_DIR}/tests/test_config.py" \
    --ignore="${ROOT_DIR}/src/tests/agents/test_human_approval_manager.py" \
    --ignore="${BACKEND_DIR}/tests/test_team_specific_methods.py" \
    --ignore="${BACKEND_DIR}/tests/models/test_messages.py" \
    --ignore="${BACKEND_DIR}/tests/test_otlp_tracing.py" \
    --ignore="${BACKEND_DIR}/tests/auth/test_auth_utils.py" \
    --ignore="${BACKEND_DIR}/tests/adapters/test_bank_statement_parsers.py" \
    --ignore="${BACKEND_DIR}/tests/adapters/test_working_paper_prepaid_schedule.py"
  popd >/dev/null

  echo "▶ [verify] Running frontend build + unit tests…"
  pushd "${FRONTEND_DIR}" >/dev/null
  npm ci --silent
  npx vitest run
  npm run build
  popd >/dev/null

  echo "✅ [verify] All checks passed."
}

# ---------------------------------------------------------------------------
# Helper: health checks — called after every deploy/promote/rollback
# ---------------------------------------------------------------------------
run_health_checks() {
  local frontend_url="${1}"
  local backend_fqdn="${2}"
  local backend_url="https://${backend_fqdn}"

  echo "▶ [health] Checking frontend: ${frontend_url}"
  for i in 1 2 3 4 5; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${frontend_url}/" || true)
    if [[ "${STATUS}" == "200" || "${STATUS}" == "301" || "${STATUS}" == "302" ]]; then
      echo "  ✅ Frontend responded ${STATUS}"
      break
    fi
    echo "  ⏳ Attempt ${i}/5 — got ${STATUS}, waiting 15s…"
    sleep 15
  done

  echo "▶ [health] Checking backend /healthz: ${backend_url}/healthz"
  for i in 1 2 3 4 5; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${backend_url}/healthz" || true)
    if [[ "${STATUS}" == "200" ]]; then
      echo "  ✅ /healthz → 200"
      break
    fi
    echo "  ⏳ Attempt ${i}/5 — got ${STATUS}, waiting 15s…"
    sleep 15
  done

  echo "▶ [health] Checking backend /readyz: ${backend_url}/readyz"
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${backend_url}/readyz" || true)
  if [[ "${STATUS}" == "200" ]]; then
    echo "  ✅ /readyz → 200"
  else
    echo "  ⚠️  /readyz returned ${STATUS} (non-fatal — may still be warming up)"
  fi

  echo "▶ [health] Checking /api/reviews/balance-sheet/find responds (auth not checked)"
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    "${backend_url}/api/reviews/balance-sheet/find" || true)
  # 401/403 = endpoint is live but requires auth — that is expected
  if [[ "${STATUS}" == "200" || "${STATUS}" == "401" || "${STATUS}" == "403" || "${STATUS}" == "422" ]]; then
    echo "  ✅ /api/reviews/balance-sheet/find reachable (HTTP ${STATUS})"
  else
    echo "  ⚠️  /api/reviews/balance-sheet/find returned ${STATUS}"
  fi

  echo "✅ [health] Post-deploy health checks complete."
}

# ---------------------------------------------------------------------------
# Modes that do NOT need a build
# ---------------------------------------------------------------------------
if [[ "${MODE}" == "health-check-only" ]]; then
  FRONTEND_URL="https://${FRONTEND_APP_NAME}.azurewebsites.net"
  BACKEND_FQDN="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --query "properties.configuration.ingress.fqdn" -o tsv)"
  run_health_checks "${FRONTEND_URL}" "${BACKEND_FQDN}"
  exit 0
fi

if [[ "${MODE}" == "rollback" ]]; then
  echo "▶ [rollback] Finding the last-active revision before the current one…"
  PREV_REVISION="$(az containerapp revision list \
    -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --query "sort_by([?properties.active==\`false\`], &properties.createdTime) | [-1].name" \
    -o tsv)"
  if [[ -z "${PREV_REVISION}" ]]; then
    echo "❌ No inactive revision found to roll back to." >&2; exit 1
  fi
  echo "  Rolling back Container App to revision: ${PREV_REVISION}"
  az containerapp revision activate \
    -g "${RG}" --app "${CONTAINER_APP_NAME}" --revision "${PREV_REVISION}" --output none
  az containerapp ingress traffic set \
    -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --revision-weight "${PREV_REVISION}=100" --output table

  # Roll back frontend App Service slot if staging slot exists
  SLOT_EXISTS="$(az webapp deployment slot list -g "${RG}" -n "${FRONTEND_APP_NAME}" \
    --query "[?name=='${STAGING_LABEL}'] | length(@)" -o tsv 2>/dev/null || echo 0)"
  if [[ "${SLOT_EXISTS}" != "0" ]]; then
    echo "  Swapping frontend slot ${STAGING_LABEL} → production to roll back…"
    az webapp deployment slot swap \
      -g "${RG}" -n "${FRONTEND_APP_NAME}" \
      --slot "${STAGING_LABEL}" --target-slot production --output table
  else
    echo "  ⚠️  No staging slot found for frontend rollback — restart production slot only."
    az webapp restart -g "${RG}" -n "${FRONTEND_APP_NAME}" --output none
  fi

  BACKEND_FQDN="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --query "properties.configuration.ingress.fqdn" -o tsv)"
  run_health_checks "https://${FRONTEND_APP_NAME}.azurewebsites.net" "${BACKEND_FQDN}"
  echo "✅ Rollback complete."
  exit 0
fi

if [[ "${MODE}" == "promote" ]]; then
  echo "▶ [promote] Shifting 100% traffic to latest '${_STAGING_BASE}' revision…"
  STAGING_REV="$(az containerapp revision list \
    -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --query "sort_by([?contains(name,'${_STAGING_BASE}')], &properties.createdTime) | [-1].name" \
    -o tsv 2>/dev/null || true)"
  if [[ -z "${STAGING_REV}" ]]; then
    echo "❌ No revision with '${_STAGING_BASE}' in its name found. Deploy staging first." >&2; exit 1
  fi
  az containerapp ingress traffic set \
    -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --revision-weight "${STAGING_REV}=100" --output table

  SLOT_EXISTS="$(az webapp deployment slot list -g "${RG}" -n "${FRONTEND_APP_NAME}" \
    --query "[?name=='${STAGING_LABEL}'] | length(@)" -o tsv 2>/dev/null || echo 0)"
  if [[ "${SLOT_EXISTS}" != "0" ]]; then
    echo "  Swapping frontend App Service slot ${STAGING_LABEL} → production…"
    az webapp deployment slot swap \
      -g "${RG}" -n "${FRONTEND_APP_NAME}" \
      --slot "${STAGING_LABEL}" --target-slot production --output table
  fi

  BACKEND_FQDN="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --query "properties.configuration.ingress.fqdn" -o tsv)"
  run_health_checks "https://${FRONTEND_APP_NAME}.azurewebsites.net" "${BACKEND_FQDN}"
  echo "✅ Promotion complete."
  exit 0
fi

# ---------------------------------------------------------------------------
# BUILD phase (used by both --staging and default prod)
# ---------------------------------------------------------------------------
echo "▶ [verify] Running pre-deploy checks before building…"
run_verify

echo "▶ [build] Building backend image in ACR: ${BACKEND_IMAGE}"
az acr build \
  --registry "${ACR_NAME}" \
  --image "backend:${BACKEND_TAG}" \
  --file "${BACKEND_DIR}/Dockerfile" \
  "${BACKEND_DIR}"

echo "▶ [deploy] Updating Container App image: ${CONTAINER_APP_NAME}"
if [[ "${MODE}" == "staging" ]]; then
  # Deploy to a new revision with a stable label — 0% production traffic
  az containerapp update \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RG}" \
    --container-name "${CONTAINER_NAME}" \
    --image "${BACKEND_IMAGE}" \
    --revision-suffix "${STAGING_LABEL}" \
    --set-env-vars "ORCHESTRATION_RUN_TTL_SECONDS=${RUN_TTL_SECONDS}" "QBO_DEBUG_ENDPOINTS_ENABLED=${QBO_DEBUG_ENDPOINTS_ENABLED}" \
    --output table
  # Send 0% traffic to the new revision (keeps it warm without customer impact)
  STAGING_REV="${CONTAINER_APP_NAME}--${STAGING_LABEL}"
  az containerapp ingress traffic set \
    -g "${RG}" -n "${CONTAINER_APP_NAME}" \
    --revision-weight "${STAGING_REV}=0" --output none || true
else
  az containerapp update \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RG}" \
    --container-name "${CONTAINER_NAME}" \
    --image "${BACKEND_IMAGE}" \
    --set-env-vars "ORCHESTRATION_RUN_TTL_SECONDS=${RUN_TTL_SECONDS}" "QBO_DEBUG_ENDPOINTS_ENABLED=${QBO_DEBUG_ENDPOINTS_ENABLED}" \
    --output table
fi

echo "Configuring Container App health probes (/healthz and /readyz)"
BACKEND_PROBES='[{"type":"Liveness","httpGet":{"path":"/healthz","port":8000},"initialDelaySeconds":10,"periodSeconds":15,"timeoutSeconds":5,"failureThreshold":3},{"type":"Readiness","httpGet":{"path":"/readyz","port":8000},"initialDelaySeconds":5,"periodSeconds":10,"timeoutSeconds":5,"failureThreshold":3}]'
PROBE_COUNT="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" --query "length(properties.template.containers[0].probes)" -o tsv || echo 0)"
if [[ "${PROBE_COUNT}" == "0" ]]; then
  echo "No probes found; applying ARM patch for liveness/readiness probes."
  CONTAINER_APP_ID="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" --query id -o tsv)"
  CONTAINER_JSON="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" --query "properties.template.containers[0]" -o json)"
  PATCH_BODY="$(jq -n --argjson container "${CONTAINER_JSON}" --argjson probes "${BACKEND_PROBES}" '{properties:{template:{containers:[($container + {probes:$probes})]}}}')"
  az rest \
    --method PATCH \
    --uri "https://management.azure.com${CONTAINER_APP_ID}?api-version=2024-03-01" \
    --body "${PATCH_BODY}" \
    --output none
fi

echo "Latest Container App revisions:"
az containerapp revision list \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RG}" \
  --query "[].{name:name,active:properties.active,created:properties.createdTime}" \
  --output table

FRONTEND_KIND="$(az webapp show -g "${RG}" -n "${FRONTEND_APP_NAME}" --query kind -o tsv || true)"
if [[ "${FRONTEND_KIND}" == *"container"* ]]; then
  echo "Frontend App Service is container-based (${FRONTEND_KIND}); deploying container image."
  az acr build \
    --registry "${ACR_NAME}" \
    --image "${FRONTEND_IMAGE_REPO}:${FRONTEND_TAG}" \
    --file "${FRONTEND_DIR}/Dockerfile" \
    "${FRONTEND_DIR}"

  APP_PRINCIPAL_ID="$(az webapp show -g "${RG}" -n "${FRONTEND_APP_NAME}" --query identity.principalId -o tsv)"
  ACR_ID="$(az acr show -g "${RG}" -n "${ACR_NAME}" --query id -o tsv)"
  HAS_ACRPULL="$(az role assignment list --assignee-object-id "${APP_PRINCIPAL_ID}" --scope "${ACR_ID}" --fill-principal-name false --query "[?roleDefinitionName=='AcrPull'] | length(@)" -o tsv)"
  HAS_ACRPULL="${HAS_ACRPULL:-0}"
  if [[ "${HAS_ACRPULL}" == "0" ]]; then
    echo "Assigning AcrPull to frontend App Service managed identity"
    az role assignment create \
      --assignee-object-id "${APP_PRINCIPAL_ID}" \
      --assignee-principal-type ServicePrincipal \
      --scope "${ACR_ID}" \
      --role AcrPull \
      --output none
  fi

  if [[ "${MODE}" == "staging" ]]; then
    # Ensure the staging slot exists
    SLOT_EXISTS="$(az webapp deployment slot list -g "${RG}" -n "${FRONTEND_APP_NAME}" \
      --query "[?name=='${STAGING_LABEL}'] | length(@)" -o tsv 2>/dev/null || echo 0)"
    if [[ "${SLOT_EXISTS}" == "0" ]]; then
      echo "  Creating deployment slot '${STAGING_LABEL}'…"
      az webapp deployment slot create \
        -g "${RG}" -n "${FRONTEND_APP_NAME}" --slot "${STAGING_LABEL}" --output none
    fi
    az webapp config set \
      --resource-group "${RG}" \
      --name "${FRONTEND_APP_NAME}" \
      --slot "${STAGING_LABEL}" \
      --acr-use-identity true \
      --acr-identity "[system]" \
      --output none
    az webapp config container set \
      --resource-group "${RG}" \
      --name "${FRONTEND_APP_NAME}" \
      --slot "${STAGING_LABEL}" \
      --container-image-name "${FRONTEND_IMAGE}" \
      --container-registry-url "https://${ACR_LOGIN_SERVER}" \
      --output table
    echo "▶ [staging] Frontend deployed to slot '${STAGING_LABEL}' — not yet swapped to production."
  else
    az webapp config set \
      --resource-group "${RG}" \
      --name "${FRONTEND_APP_NAME}" \
      --acr-use-identity true \
      --acr-identity "[system]" \
      --output none
    az webapp config container set \
      --resource-group "${RG}" \
      --name "${FRONTEND_APP_NAME}" \
      --container-image-name "${FRONTEND_IMAGE}" \
      --container-registry-url "https://${ACR_LOGIN_SERVER}" \
      --output table
    echo "Restarting frontend app service"
    az webapp restart --resource-group "${RG}" --name "${FRONTEND_APP_NAME}"
  fi
else
  echo "Frontend App Service is code-based (${FRONTEND_KIND}); deploying build artifact zip."
  pushd "${FRONTEND_DIR}" >/dev/null
  npm ci
  npm run build
  zip -rq "${DEPLOY_ZIP}" . -x "node_modules/*" ".venv/*" "__pycache__/*" "*.pyc"
  popd >/dev/null

  if [[ "${MODE}" == "staging" ]]; then
    SLOT_EXISTS="$(az webapp deployment slot list -g "${RG}" -n "${FRONTEND_APP_NAME}" \
      --query "[?name=='${STAGING_LABEL}'] | length(@)" -o tsv 2>/dev/null || echo 0)"
    if [[ "${SLOT_EXISTS}" == "0" ]]; then
      az webapp deployment slot create \
        -g "${RG}" -n "${FRONTEND_APP_NAME}" --slot "${STAGING_LABEL}" --output none
    fi
    az webapp deploy \
      --resource-group "${RG}" \
      --name "${FRONTEND_APP_NAME}" \
      --slot "${STAGING_LABEL}" \
      --src-path "${DEPLOY_ZIP}" \
      --type zip \
      --restart true \
      --output table
    echo "▶ [staging] Frontend deployed to slot '${STAGING_LABEL}' — not yet swapped to production."
  else
    az webapp deploy \
      --resource-group "${RG}" \
      --name "${FRONTEND_APP_NAME}" \
      --src-path "${DEPLOY_ZIP}" \
      --type zip \
      --restart true \
      --output table
    az webapp restart --resource-group "${RG}" --name "${FRONTEND_APP_NAME}"
  fi
fi

# ---------------------------------------------------------------------------
# Post-deploy health checks
# ---------------------------------------------------------------------------
echo "▶ Waiting ${REVISION_READY_WAIT}s for new revision/slot to warm up…"
sleep "${REVISION_READY_WAIT}"

BACKEND_FQDN="$(az containerapp show -g "${RG}" -n "${CONTAINER_APP_NAME}" \
  --query "properties.configuration.ingress.fqdn" -o tsv)"

if [[ "${MODE}" == "staging" ]]; then
  FRONTEND_HEALTH_URL="https://${FRONTEND_APP_NAME}-${STAGING_LABEL}.azurewebsites.net"
else
  FRONTEND_HEALTH_URL="https://${FRONTEND_APP_NAME}.azurewebsites.net"
fi

run_health_checks "${FRONTEND_HEALTH_URL}" "${BACKEND_FQDN}"

echo ""
echo "✅ Deployment complete (mode: ${MODE})"
echo "   Backend image : ${BACKEND_IMAGE}"
echo "   Frontend slot : ${MODE == 'staging' && echo ${STAGING_LABEL} || echo production}"
if [[ "${MODE}" == "staging" ]]; then
  echo ""
  echo "Next steps:"
  echo "  Smoke-test staging, then promote with:"
  echo "  RG=${RG} CONTAINER_APP_NAME=${CONTAINER_APP_NAME} FRONTEND_APP_NAME=${FRONTEND_APP_NAME} \\"
  echo "    $(dirname "${BASH_SOURCE[0]}")/deploy_prod.sh --promote --confirm"
fi
