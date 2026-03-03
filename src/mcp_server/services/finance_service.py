"""
Finance MCP tools for balance sheet review workflows.
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import quote
from typing import Any

import httpx
from fastmcp.server.dependencies import get_access_token, get_http_headers

from core.factory import Domain, MCPToolBase
from utils.formatters import format_error_response, format_success_response


_DEFAULT_TIMEOUT = 30.0
_WAIT_DEFAULT_TIMEOUT_SECONDS = 120
_WAIT_MAX_TIMEOUT_SECONDS = 600
_WAIT_DEFAULT_POLL_SECONDS = 3
_WAIT_MAX_POLL_SECONDS = 30
_TERMINAL_RUN_STATUSES = {"done", "fetched", "raw", "failed"}
LOGGER = logging.getLogger(__name__)


def _is_truthy_env(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _backend_url() -> str:
    url = os.getenv("BACKEND_URL", "").strip() or os.getenv("BACKEND_API_URL", "").strip()
    if not url:
        raise ValueError("BACKEND_URL is not configured for finance tools.")
    return url.rstrip("/")


def _frontend_url() -> str | None:
    raw = str(os.getenv("FRONTEND_SITE_NAME", "")).strip()
    if not raw:
        return None
    primary = raw.split(",")[0].strip()
    if not primary:
        return None
    return primary.rstrip("/")


def _resolve_user_auth_header() -> dict[str, str]:
    """Resolve caller auth from MCP request context for backend fan-out calls."""
    headers = get_http_headers(include_all=True)

    # Preferred explicit user token injected by backend MCP client.
    user_token = str(headers.get("x-user-auth-token") or "").strip()
    if user_token:
        return {"authorization": f"Bearer {user_token}"}

    # Fallback to existing Authorization header if present.
    authorization = str(headers.get("authorization") or "").strip()
    if authorization:
        if authorization.lower().startswith("bearer "):
            return {"authorization": authorization}
        return {"authorization": f"Bearer {authorization}"}

    # Final fallback to access token from FastMCP auth middleware context.
    try:
        token = get_access_token()
    except Exception:
        token = None
    if token and str(getattr(token, "token", "")).strip():
        return {"authorization": f"Bearer {token.token}"}
    return {}


def _request_json(method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict[str, Any]:
    url = f"{_backend_url()}{path}"
    outbound_headers = _resolve_user_auth_header()
    if _is_truthy_env("MCP_REQUIRE_USER_AUTH", default=False):
        if "authorization" not in {str(k).lower() for k in outbound_headers.keys()}:
            raise RuntimeError(
                "Missing user auth token in MCP request context. "
                "Sign in again and retry so QBO calls run under the correct user identity."
            )
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        resp = client.request(
            method,
            url,
            json=json,
            params=params,
            headers=outbound_headers or None,
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Backend error {resp.status_code}: {payload}")
    if not isinstance(payload, dict):
        return {"data": payload}
    return payload


def _summarize_run(payload: dict[str, Any]) -> dict[str, Any]:
    totals = payload.get("totals") or {}
    findings = payload.get("findings") or []

    # Build compact per-account rows so agents can render a full balance sheet table.
    bs_rows: list[dict[str, Any]] = []
    bs_view = payload.get("balance_sheet_view")
    if isinstance(bs_view, dict):
        for row in (bs_view.get("accounts") or []):
            if not isinstance(row, dict):
                continue
            acct = row.get("account") or {}
            hits = row.get("rule_hits") or []
            first_hit = hits[0] if hits and isinstance(hits[0], dict) else {}
            bs_rows.append({
                "account": str(acct.get("name") or acct.get("account_ref") or ""),
                "section": str(acct.get("type") or ""),
                "balance": str(acct.get("balance") or "0"),
                "is_total": bool(row.get("is_total", False)),
                "status": str(row.get("status") or "NOT_APPLICABLE"),
                "flag": str(first_hit.get("summary") or "") if hits else "",
                "action": str(first_hit.get("human_action") or "") if hits else "",
            })

    return {
        "status": payload.get("status"),
        "run_id": payload.get("run_id") or payload.get("id"),
        "summary": payload.get("summary"),
        "totals": totals,
        "findings_count": len(findings) if isinstance(findings, list) else None,
        "hitl_requests": payload.get("hitl_requests") or [],
        "snapshot_keys": payload.get("snapshot_keys") or {},
        "artifact_keys": payload.get("artifact_keys") or {},
        "error": payload.get("error"),
        "balance_sheet_rows": bs_rows,
    }


def _status_next_step_guidance(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "raw":
        return (
            "Raw fetch is complete. Next: NormalizationAgent should call "
            "bs_normalize_data, then wait_for_balance_sheet_review until status is fetched or done."
        )
    if normalized == "fetched":
        return "Data is already normalized. Next: RulesAgent should call bs_run_rules."
    if normalized == "done":
        return (
            "Rules already ran on this run_id. Next: ReportAgent should call bs_get_findings "
            "(or RulesAgent may call bs_run_rules idempotently)."
        )
    if normalized == "failed":
        return "Run failed. Start a new run via bs_fetch_data."
    return "Status is unknown. Call get_balance_sheet_review for details."


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, dict) and not value:
            continue
        compact[key] = value
    return compact


def _call_qbo_data_endpoint(*, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request_json("POST", f"/api/qbo/data{path}", json=_compact_payload(payload))


def _format_qbo_data_success(action: str, payload: dict[str, Any], summary: str | None = None) -> str:
    details = {
        "tool": payload.get("tool"),
        "client_id": payload.get("client_id"),
        "realm_id": payload.get("realm_id"),
    }
    details.update(payload)
    return format_success_response(action, details, summary=summary)


class FinanceService(MCPToolBase):
    """Finance tools for balance sheet review orchestration."""

    def __init__(self) -> None:
        super().__init__(Domain.FINANCE)

    def register_tools(self, mcp) -> None:
        """Register finance tools with the MCP server."""

        @mcp.tool(tags={self.domain.value})
        def qbo_connection_status(client_id: str) -> str:
            """Check if a client has an active QBO connection."""
            normalized = (client_id or "").strip()
            if not normalized:
                return format_error_response("client_id is required.", context="checking QBO connection")

            frontend_url = _frontend_url()
            connect_url = (
                f"{frontend_url}/qbo/connect?client_id={quote(normalized)}"
                if frontend_url
                else f"{_backend_url()}/api/qbo/connect/start?client_id={quote(normalized)}"
            )
            try:
                payload = _request_json(
                    "GET",
                    "/api/qbo/status",
                    params={"client_id": normalized},
                )
                resolved_client_id = normalized
                if not payload.get("connected") and normalized.lower() != normalized:
                    fallback_id = normalized.lower()
                    fallback_payload = _request_json(
                        "GET",
                        "/api/qbo/status",
                        params={"client_id": fallback_id},
                    )
                    if fallback_payload.get("connected"):
                        payload = fallback_payload
                        resolved_client_id = fallback_id

                connected = bool(payload.get("connected"))
                suggestions = payload.get("suggested_client_ids") or []
                payload_resolved = str(payload.get("resolved_client_id") or "").strip()
                if payload_resolved:
                    resolved_client_id = payload_resolved
                connect_url = (
                    f"{frontend_url}/qbo/connect?client_id={quote(resolved_client_id)}"
                    if frontend_url
                    else f"{_backend_url()}/api/qbo/connect/start?client_id={quote(resolved_client_id)}"
                )
                details = {
                    "client_id_input": client_id,
                    "client_id_resolved": resolved_client_id,
                    "connected": connected,
                    "realm_id": payload.get("realm_id"),
                    "store_mode": payload.get("store_mode"),
                    "reason": payload.get("reason"),
                    "suggested_client_ids": suggestions,
                    "connect_url": connect_url,
                }
                if connected:
                    summary = "QBO connection is active."
                elif suggestions:
                    joined = ", ".join(suggestions)
                    summary = (
                        f"QBO connection missing. Did you mean {joined}? "
                        f"Open this URL to connect: {connect_url}"
                    )
                else:
                    summary = f"QBO connection missing. Open this URL to connect: {connect_url}"
                return format_success_response("QBO Connection Status", details, summary)
            except Exception as e:
                details = {
                    "client_id_input": client_id,
                    "client_id_resolved": normalized,
                    "connected": False,
                    "reason": str(e),
                    "connect_url": connect_url,
                }
                return format_success_response(
                    "QBO Connection Status",
                    details,
                    summary=(
                        "Unable to verify QBO connection. "
                        f"Ask the user to open this URL to connect: {connect_url}"
                    ),
                )

        @mcp.tool(tags={self.domain.value})
        def start_balance_sheet_review(
            client_id: str,
            period_end: str,
            notes: str | None = None,
        ) -> str:
            """Start a balance sheet review run for a client and period end."""
            try:
                payload = _request_json(
                    "POST",
                    "/api/reviews/balance-sheet/run",
                    json={
                        "client_id": client_id,
                        "period_end": period_end,
                        "notes": notes,
                    },
                )
                details = {
                    "client_id": client_id,
                    "period_end": period_end,
                    "run_id": payload.get("run_id"),
                    "status": payload.get("status"),
                }
                return format_success_response("Balance Sheet Review Started", details)
            except Exception as e:
                return format_error_response(str(e), context="starting balance sheet review")

        @mcp.tool(tags={self.domain.value})
        def get_or_create_balance_sheet_review(
            client_id: str,
            period_end: str,
            notes: str | None = None,
        ) -> str:
            """
            Idempotent entry-point for starting a balance sheet review.

            1. Checks whether an active (non-failed) run already exists for
               (client_id, period_end).
            2. If one exists, returns it immediately WITHOUT creating a new run.
            3. If none exists, starts a new run exactly once.

            Always call this tool instead of `start_balance_sheet_review` so that
            orchestrator replans and agent retries never create duplicate runs.
            Returns a single run_id that ALL downstream agents must use.
            """
            try:
                # --- 1. Look up any existing active run ---
                try:
                    existing = _request_json(
                        "GET",
                        f"/api/reviews/balance-sheet/find?client_id={quote(client_id)}&period_end={period_end}",
                    )
                    existing_run_id = existing.get("run_id") or existing.get("id")
                    existing_status = str(existing.get("status") or "").lower()
                    if existing_run_id and existing_status != "failed":
                        details = {
                            "client_id": client_id,
                            "period_end": period_end,
                            "run_id": existing_run_id,
                            "status": existing_status,
                            "idempotent": True,
                            "reused": True,
                        }
                        LOGGER.info(
                            "get_or_create: reusing existing run_id=%s status=%s",
                            existing_run_id,
                            existing_status,
                        )
                        return format_success_response(
                            "Balance Sheet Review (Existing Run)",
                            details,
                            summary=(
                                f"Reusing existing run {existing_run_id} "
                                f"(status={existing_status}). "
                                "Do NOT call start_balance_sheet_review again."
                            ),
                        )
                except Exception as lookup_err:
                    # 404 = no existing run → fall through to create
                    status_code = getattr(
                        getattr(lookup_err, "response", None), "status_code", None
                    )
                    if status_code != 404:
                        LOGGER.warning("get_or_create lookup failed: %s", lookup_err)

                # --- 2. No active run found — create one ---
                payload = _request_json(
                    "POST",
                    "/api/reviews/balance-sheet/run",
                    json={
                        "client_id": client_id,
                        "period_end": period_end,
                        "notes": notes,
                    },
                )
                details = {
                    "client_id": client_id,
                    "period_end": period_end,
                    "run_id": payload.get("run_id"),
                    "status": payload.get("status"),
                    "idempotent": True,
                    "reused": False,
                }
                LOGGER.info(
                    "get_or_create: started new run_id=%s", payload.get("run_id")
                )
                return format_success_response(
                    "Balance Sheet Review Started (New Run)",
                    details,
                    summary=(
                        f"Started new run {payload.get('run_id')}. "
                        "All agents must use this run_id."
                    ),
                )
            except Exception as e:
                return format_error_response(
                    str(e), context="get-or-create balance sheet review"
                )

        @mcp.tool(tags={self.domain.value})
        def run_balance_sheet_review(
            client_id: str,
            period_end: str,
            notes: str | None = None,
        ) -> str:
            """
            Run a complete balance sheet review synchronously and return results.

            This is the preferred tool for ReviewAgent. It calls the backend pipeline
            (fetch QBO data → normalize → run 22 rules → generate summary) and blocks
            until the pipeline completes (typically 25-45 seconds), then returns the
            complete run record including findings, balance_sheet_rows, and hitl_requests.

            Unlike start_balance_sheet_review + wait_for_balance_sheet_review, this tool
            makes a single HTTP call with no polling loop.

            Always starts a fresh pipeline run — never returns cached results.
            """
            try:
                # Call the synchronous endpoint — blocks until pipeline completes.
                # Use a 90-second timeout: well above 25-45s target, below ALB default.
                url = f"{_backend_url()}/api/reviews/balance-sheet/run"
                outbound_headers = _resolve_user_auth_header()
                body = {
                    "client_id": client_id,
                    "period_end": period_end,
                    "notes": notes,
                }
                with httpx.Client(timeout=90.0) as client_http:
                    resp = client_http.post(
                        url,
                        json=body,
                        params={"await": "true"},
                        headers=outbound_headers or None,
                    )
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"raw": resp.text}
                if resp.status_code >= 400:
                    raise RuntimeError(f"Backend error {resp.status_code}: {payload}")
                if not isinstance(payload, dict):
                    payload = {"data": payload}

                details = _summarize_run(payload)
                run_id = payload.get("run_id") or payload.get("id") or "unknown"
                status = str(details.get("status") or "").lower()
                summary = (
                    f"Balance sheet review complete for {client_id} period {period_end}. "
                    f"Run ID: {run_id}. Status: {status}."
                )
                LOGGER.info(
                    "run_balance_sheet_review complete run_id=%s status=%s", run_id, status
                )
                return format_success_response("Balance Sheet Review Complete", details, summary=summary)
            except Exception as e:
                return format_error_response(str(e), context="running balance sheet review")

        @mcp.tool(tags={self.domain.value})
        def get_balance_sheet_review(run_id: str) -> str:
            """Fetch the status/results for a balance sheet review run."""
            try:
                payload = _request_json(
                    "GET",
                    f"/api/reviews/balance-sheet/runs/{run_id}",
                )
                details = _summarize_run(payload)
                return format_success_response("Balance Sheet Review Status", details)
            except Exception as e:
                return format_error_response(str(e), context="fetching balance sheet review status")

        @mcp.tool(tags={self.domain.value})
        def wait_for_balance_sheet_review(
            run_id: str,
            timeout_seconds: int = _WAIT_DEFAULT_TIMEOUT_SECONDS,
            poll_seconds: int = _WAIT_DEFAULT_POLL_SECONDS,
        ) -> str:
            """Poll until a balance sheet review run completes or fails."""
            try:
                timeout_seconds = _clamp_int(
                    _coerce_int(timeout_seconds, _WAIT_DEFAULT_TIMEOUT_SECONDS),
                    1,
                    _clamp_int(
                        _coerce_int(
                            os.getenv(
                                "MCP_BS_WAIT_MAX_TIMEOUT_SECONDS",
                                str(_WAIT_MAX_TIMEOUT_SECONDS),
                            ),
                            _WAIT_MAX_TIMEOUT_SECONDS,
                        ),
                        1,
                        600,
                    ),
                )
                poll_seconds = _clamp_int(
                    _coerce_int(poll_seconds, _WAIT_DEFAULT_POLL_SECONDS),
                    1,
                    _clamp_int(
                        _coerce_int(
                            os.getenv(
                                "MCP_BS_WAIT_MAX_POLL_SECONDS",
                                str(_WAIT_MAX_POLL_SECONDS),
                            ),
                            _WAIT_MAX_POLL_SECONDS,
                        ),
                        1,
                        60,
                    ),
                )

                LOGGER.info(
                    "wait_for_balance_sheet_review start run_id=%s timeout_seconds=%s poll_seconds=%s",
                    run_id,
                    timeout_seconds,
                    poll_seconds,
                )

                deadline = time.time() + timeout_seconds
                last_payload: dict[str, Any] = {}
                poll_count = 0
                while time.time() < deadline:
                    last_payload = _request_json(
                        "GET",
                        f"/api/reviews/balance-sheet/runs/{run_id}",
                    )
                    poll_count += 1
                    status = str(last_payload.get("status") or "").lower()
                    if status in _TERMINAL_RUN_STATUSES:
                        break
                    time.sleep(poll_seconds)

                details = _summarize_run(last_payload) if last_payload else {"run_id": run_id}
                status = str(details.get("status") or "").lower()
                terminal = status in _TERMINAL_RUN_STATUSES
                details["terminal"] = terminal
                details["poll_count"] = poll_count
                details["wait_timeout_seconds"] = timeout_seconds
                if not terminal:
                    details["next_poll_seconds"] = poll_seconds
                    details["timed_out"] = True
                    summary = (
                        f"Run {run_id} is still {status or 'running'}. "
                        "Continue polling; this response is non-terminal."
                    )
                    action = "Balance Sheet Review In Progress"
                else:
                    details["timed_out"] = False
                    summary = (
                        f"Run {run_id} reached terminal status: {status}. "
                        f"{_status_next_step_guidance(status)}"
                    )
                    action = "Balance Sheet Review Completed"

                LOGGER.info(
                    "wait_for_balance_sheet_review end run_id=%s status=%s terminal=%s poll_count=%s",
                    run_id,
                    status or "unknown",
                    terminal,
                    poll_count,
                )
                return format_success_response(action, details, summary=summary)
            except Exception as e:
                return format_error_response(str(e), context="waiting for balance sheet review")

        @mcp.tool(tags={self.domain.value})
        def list_snapshots(run_id: str) -> str:
            """List snapshot and artifact keys produced by a balance sheet run."""
            try:
                payload = _request_json(
                    "GET",
                    f"/api/reviews/balance-sheet/runs/{run_id}/snapshots",
                )
                details = {
                    "run_id": payload.get("run_id"),
                    "client_id": payload.get("client_id"),
                    "period_end": payload.get("period_end"),
                    "status": payload.get("status"),
                    "snapshot_count": payload.get("snapshot_count"),
                    "artifact_count": payload.get("artifact_count"),
                    "snapshot_keys": payload.get("snapshot_keys") or {},
                    "artifact_keys": payload.get("artifact_keys") or {},
                }
                return format_success_response("Balance Sheet Snapshot List", details)
            except Exception as e:
                return format_error_response(str(e), context="listing snapshots for run")

        @mcp.tool(tags={self.domain.value})
        def get_snapshot(snapshot_key: str) -> str:
            """Fetch stored snapshot JSON content by snapshot key."""
            try:
                payload = _request_json(
                    "GET",
                    "/api/reviews/snapshots/content",
                    params={"snapshot_key": snapshot_key},
                )
                details = {
                    "snapshot_key": payload.get("snapshot_key"),
                    "source": payload.get("source"),
                    "content_type": payload.get("content_type"),
                    "size_bytes": payload.get("size_bytes"),
                    "snapshot": payload.get("snapshot"),
                }
                return format_success_response("Snapshot Content", details)
            except Exception as e:
                return format_error_response(str(e), context="retrieving snapshot content")

        @mcp.tool(tags={self.domain.value})
        def get_artifact(artifact_key: str) -> str:
            """Fetch stored artifact content by artifact key (json/text/base64)."""
            try:
                payload = _request_json(
                    "GET",
                    "/api/reviews/artifacts/content",
                    params={"artifact_key": artifact_key},
                )
                details = {
                    "artifact_key": payload.get("artifact_key"),
                    "source": payload.get("source"),
                    "content_type": payload.get("content_type"),
                    "encoding": payload.get("encoding"),
                    "size_bytes": payload.get("size_bytes"),
                    "artifact": payload.get("artifact"),
                    "artifact_base64": payload.get("artifact_base64"),
                }
                return format_success_response("Artifact Content", details)
            except Exception as e:
                return format_error_response(str(e), context="retrieving artifact content")

        @mcp.tool(tags={self.domain.value})
        def drive_connection_status(client_id: str | None = None) -> str:
            """Check Google Drive connector status for a client."""
            try:
                params = {"client_id": client_id} if client_id else None
                payload = _request_json("GET", "/api/drive/status", params=params)
                details = {
                    "client_id": payload.get("client_id"),
                    "connected": payload.get("connected"),
                    "reason": payload.get("reason"),
                    "root_folder_id": payload.get("root_folder_id"),
                    "evidence_manifest_file_id": payload.get("evidence_manifest_file_id"),
                    "folder_accessible": payload.get("folder_accessible"),
                    "supports_all_drives": payload.get("supports_all_drives"),
                    "include_items_from_all_drives": payload.get("include_items_from_all_drives"),
                }
                summary = "Google Drive connector is active." if payload.get("connected") else "Google Drive connector is not configured."
                return format_success_response("Drive Connection Status", details, summary=summary)
            except Exception as e:
                return format_error_response(str(e), context="checking Drive connection")

        @mcp.tool(tags={self.domain.value})
        def drive_list_files(
            client_id: str | None = None,
            folder_id: str | None = None,
            query: str | None = None,
            page_size: int = 100,
        ) -> str:
            """List Google Drive files for a folder."""
            try:
                payload = _request_json(
                    "POST",
                    "/api/drive/files/list",
                    json={
                        "client_id": client_id,
                        "folder_id": folder_id,
                        "query": query,
                        "page_size": page_size,
                    },
                )
                details = {
                    "client_id": payload.get("client_id"),
                    "folder_id": payload.get("folder_id"),
                    "count": payload.get("count"),
                    "files": payload.get("files") or [],
                }
                return format_success_response("Drive Files List", details)
            except Exception as e:
                return format_error_response(str(e), context="listing Drive files")

        @mcp.tool(tags={self.domain.value})
        def drive_get_file(
            file_id: str,
            client_id: str | None = None,
            export_mime_type: str | None = None,
            max_inline_bytes: int = 300000,
        ) -> str:
            """Get Google Drive file metadata + inline content (text/json/base64)."""
            try:
                payload = _request_json(
                    "POST",
                    "/api/drive/files/get",
                    json={
                        "client_id": client_id,
                        "file_id": file_id,
                        "export_mime_type": export_mime_type,
                        "max_inline_bytes": max_inline_bytes,
                    },
                )
                details = {
                    "client_id": payload.get("client_id"),
                    "file_id": payload.get("file_id"),
                    "content_type": payload.get("content_type"),
                    "size_bytes": payload.get("size_bytes"),
                    "content_omitted": payload.get("content_omitted"),
                    "metadata": payload.get("metadata"),
                    "encoding": payload.get("encoding"),
                    "content_json": payload.get("content_json"),
                    "content_text": payload.get("content_text"),
                    "content_base64": payload.get("content_base64"),
                }
                return format_success_response("Drive File Content", details)
            except Exception as e:
                return format_error_response(str(e), context="retrieving Drive file")

        @mcp.tool(tags={self.domain.value})
        def drive_get_evidence_manifest(
            client_id: str | None = None,
            file_id: str | None = None,
        ) -> str:
            """Load and parse Drive evidence manifest JSON into evidence items."""
            try:
                payload = _request_json(
                    "POST",
                    "/api/drive/evidence/manifest",
                    json={
                        "client_id": client_id,
                        "file_id": file_id,
                    },
                )
                details = {
                    "client_id": payload.get("client_id"),
                    "file_id": payload.get("file_id"),
                    "evidence_count": payload.get("evidence_count"),
                    "evidence_types": payload.get("evidence_types") or [],
                    "evidence_items": payload.get("evidence_items") or [],
                }
                return format_success_response("Drive Evidence Manifest", details)
            except Exception as e:
                return format_error_response(str(e), context="retrieving Drive evidence manifest")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_profit_and_loss(
            client_id: str,
            start_date: str,
            end_date: str,
            basis: str = "Accrual",
            summarize_by: str | None = None,
            filters: dict[str, Any] | None = None,
        ) -> str:
            """Get QBO Profit and Loss report for a date range."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/profit-and-loss",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "basis": basis,
                        "summarize_by": summarize_by,
                        "filters": filters,
                    },
                )
                return _format_qbo_data_success("QBO Profit and Loss", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO profit and loss")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_balance_sheet(
            client_id: str,
            as_of_date: str,
            basis: str = "Accrual",
            summarize_by: str | None = None,
            filters: dict[str, Any] | None = None,
        ) -> str:
            """Get QBO Balance Sheet report as of a date."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/balance-sheet",
                    payload={
                        "client_id": client_id,
                        "as_of_date": as_of_date,
                        "basis": basis,
                        "summarize_by": summarize_by,
                        "filters": filters,
                    },
                )
                return _format_qbo_data_success("QBO Balance Sheet", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO balance sheet")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_cash_flow(
            client_id: str,
            start_date: str,
            end_date: str,
            basis: str = "Accrual",
            filters: dict[str, Any] | None = None,
        ) -> str:
            """Get QBO cash flow report for a date range."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/cash-flow",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "basis": basis,
                        "filters": filters,
                    },
                )
                return _format_qbo_data_success("QBO Cash Flow", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO cash flow")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_trial_balance(
            client_id: str,
            start_date: str,
            end_date: str,
            basis: str = "Accrual",
            filters: dict[str, Any] | None = None,
        ) -> str:
            """Get QBO trial balance report for a date range."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/trial-balance",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "basis": basis,
                        "filters": filters,
                    },
                )
                return _format_qbo_data_success("QBO Trial Balance", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO trial balance")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_gl_detail(
            client_id: str,
            start_date: str,
            end_date: str,
            account_id: str | None = None,
            class_name: str | None = None,
            location: str | None = None,
            customer: str | None = None,
            vendor: str | None = None,
            min_amount: float | None = None,
            basis: str = "Accrual",
            filters: dict[str, Any] | None = None,
        ) -> str:
            """Get QBO general-ledger detail with optional drilldown filters."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/gl-detail",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "basis": basis,
                        "account_id": account_id,
                        "class_name": class_name,
                        "location": location,
                        "customer": customer,
                        "vendor": vendor,
                        "min_amount": min_amount,
                        "filters": filters,
                    },
                )
                return _format_qbo_data_success("QBO GL Detail", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO GL detail")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_transactions_by_account(
            client_id: str,
            account_id: str,
            start_date: str,
            end_date: str,
            include_splits: bool = True,
            basis: str = "Accrual",
            filters: dict[str, Any] | None = None,
        ) -> str:
            """Get QBO transactions by account for a date range."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/transactions/by-account",
                    payload={
                        "client_id": client_id,
                        "account_id": account_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "include_splits": include_splits,
                        "basis": basis,
                        "filters": filters,
                    },
                )
                return _format_qbo_data_success("QBO Transactions by Account", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO transactions by account")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_transaction(transaction_id: str, client_id: str | None = None) -> str:
            """Get a full QBO transaction object by id."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/transaction",
                    payload={
                        "client_id": client_id,
                        "transaction_id": transaction_id,
                    },
                )
                return _format_qbo_data_success("QBO Transaction", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO transaction")

        @mcp.tool(tags={self.domain.value})
        def qbo_list_accounts(client_id: str, include_inactive: bool = True) -> str:
            """List QBO chart of accounts with account types and status."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/accounts",
                    payload={
                        "client_id": client_id,
                        "include_inactive": include_inactive,
                    },
                )
                return _format_qbo_data_success("QBO Accounts", payload)
            except Exception as e:
                return format_error_response(str(e), context="listing QBO accounts")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_ar_aging(client_id: str, as_of_date: str) -> str:
            """Get QBO AR aging (summary and detail) as of a date."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/ar-aging",
                    payload={
                        "client_id": client_id,
                        "as_of_date": as_of_date,
                    },
                )
                return _format_qbo_data_success("QBO AR Aging", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO AR aging")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_ap_aging(client_id: str, as_of_date: str) -> str:
            """Get QBO AP aging (summary and detail) as of a date."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/ap-aging",
                    payload={
                        "client_id": client_id,
                        "as_of_date": as_of_date,
                    },
                )
                return _format_qbo_data_success("QBO AP Aging", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO AP aging")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_open_invoices(
            client_id: str,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> str:
            """Get open invoices from QBO with optional date filters."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/open-invoices",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
                return _format_qbo_data_success("QBO Open Invoices", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO open invoices")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_open_bills(
            client_id: str,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> str:
            """Get open bills from QBO with optional date filters."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/open-bills",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
                return _format_qbo_data_success("QBO Open Bills", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving QBO open bills")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_bank_reconciliation_status(
            client_id: str,
            bank_account_id: str,
            as_of_date: str | None = None,
        ) -> str:
            """Get best-effort QBO bank reconciliation status for an account."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/bank-reconciliation-status",
                    payload={
                        "client_id": client_id,
                        "bank_account_id": bank_account_id,
                        "as_of_date": as_of_date,
                    },
                )
                return _format_qbo_data_success("QBO Bank Reconciliation Status", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving bank reconciliation status")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_sales_tax_liability(
            client_id: str,
            start_date: str,
            end_date: str,
            basis: str = "Accrual",
        ) -> str:
            """Get QBO sales tax liability report (or best-effort fallback)."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/sales-tax-liability",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "basis": basis,
                    },
                )
                return _format_qbo_data_success("QBO Sales Tax Liability", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving sales tax liability")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_sales_tax_returns(
            client_id: str,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> str:
            """Get QBO sales tax returns/payments with optional date filters."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/sales-tax-returns",
                    payload={
                        "client_id": client_id,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
                return _format_qbo_data_success("QBO Sales Tax Returns", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving sales tax returns")

        @mcp.tool(tags={self.domain.value})
        def qbo_get_payroll_liabilities(
            client_id: str,
            as_of_date: str | None = None,
        ) -> str:
            """Get best-effort QBO payroll liabilities context for review."""
            try:
                payload = _call_qbo_data_endpoint(
                    path="/payroll-liabilities",
                    payload={
                        "client_id": client_id,
                        "as_of_date": as_of_date,
                    },
                )
                return _format_qbo_data_success("QBO Payroll Liabilities", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving payroll liabilities")

        # ── Balance Sheet Review Pipeline Tools (layered, no duplication) ─────────

        @mcp.tool(tags={self.domain.value})
        def bs_fetch_data(
            client_id: str,
            period_end: str,
            notes: str | None = None,
        ) -> str:
            """Start a balance sheet raw-fetch-only run (QBO API calls only; does NOT normalize or run rules).
            Idempotent: reuses an existing non-failed run for the same client and period.
            Returns run_id. Use wait_for_balance_sheet_review(poll_seconds=2) and interpret:
            - status='raw': fetch complete, NormalizationAgent should call bs_normalize_data
            - status='fetched': already normalized, RulesAgent can call bs_run_rules
            - status='done': rules already ran; ReportAgent can call bs_get_findings directly
            ConnectorAgent MUST use this tool instead of start_balance_sheet_review for new flows.
            """
            try:
                # Check for existing non-failed run first (idempotency)
                try:
                    existing = _request_json(
                        "GET",
                        f"/api/reviews/balance-sheet/find?client_id={quote(client_id)}&period_end={period_end}",
                    )
                    existing_run_id = existing.get("run_id") or existing.get("id")
                    existing_status = str(existing.get("status") or "").lower()
                    if existing_run_id and existing_status != "failed":
                        next_step = _status_next_step_guidance(existing_status)
                        details = {
                            "client_id": client_id,
                            "period_end": period_end,
                            "run_id": existing_run_id,
                            "status": existing_status,
                            "reused": True,
                            "next_step": next_step,
                        }
                        return format_success_response(
                            "Balance Sheet Fetch (Existing Run)",
                            details,
                            summary=(
                                f"Reusing existing run {existing_run_id} (status={existing_status}). "
                                f"{next_step}"
                            ),
                        )
                except Exception as lookup_err:
                    status_code = getattr(getattr(lookup_err, "response", None), "status_code", None)
                    if status_code != 404:
                        LOGGER.warning("bs_fetch_data lookup failed: %s", lookup_err)

                payload = _request_json(
                    "POST",
                    "/api/reviews/balance-sheet/fetch",
                    json={"client_id": client_id, "period_end": period_end, "notes": notes},
                )
                details = {
                    "client_id": client_id,
                    "period_end": period_end,
                    "run_id": payload.get("run_id"),
                    "status": payload.get("status"),
                    "reused": False,
                }
                return format_success_response(
                    "Balance Sheet Fetch Started",
                    details,
                    summary=(
                        f"Fetch started for run {payload.get('run_id')}. "
                        "Use wait_for_balance_sheet_review(poll_seconds=2) to wait for status=raw, "
                        "then NormalizationAgent calls bs_normalize_data to normalize "
                        "(sets status=fetched), then RulesAgent calls bs_run_rules."
                    ),
                )
            except Exception as e:
                return format_error_response(str(e), context="starting balance sheet fetch")

        @mcp.tool(tags={self.domain.value})
        def bs_normalize_data(run_id: str) -> str:
            """Run the normalization phase on a raw-fetched balance sheet run (synchronous).
            Prefer calling after wait_for_balance_sheet_review returns status='raw'.
            If the run is already 'fetched' or 'done', this call is idempotent and should
            return the existing run details without failure.
            Runs build_qbo_snapshots, build_qbo_aging_evidence, build_qbo_tax_evidence on the
            raw QBO payloads and stores a normalized review_inputs artifact.
            Sets run status to 'fetched' on success (or keeps 'done' for already completed runs).
            NormalizationAgent is the ONLY agent that should call this tool.
            After calling this tool, call wait_for_balance_sheet_review(run_id, poll_seconds=2)
            and accept status in {'fetched','done'} before the RulesAgent calls bs_run_rules.
            """
            try:
                payload = _request_json(
                    "POST",
                    f"/api/reviews/balance-sheet/{run_id}/normalize",
                    json={},
                )
                details = _summarize_run(payload)
                return format_success_response("Balance Sheet Normalization Complete", details)
            except Exception as e:
                return format_error_response(str(e), context="running balance sheet normalization")

        @mcp.tool(tags={self.domain.value})
        def bs_list_rules(client_id: str | None = None) -> str:
            """List all available balance sheet rules with their IDs and titles.
            RulesAgent uses this to discover rule IDs before calling bs_run_rules with a specific subset.
            """
            try:
                payload = _request_json("GET", "/api/reviews/rules")
                details = {
                    "rules": payload.get("rules") or [],
                    "count": payload.get("count"),
                }
                return format_success_response("Available Balance Sheet Rules", details)
            except Exception as e:
                return format_error_response(str(e), context="listing balance sheet rules")

        @mcp.tool(tags={self.domain.value})
        def bs_run_rules(
            run_id: str,
            rule_ids: list[str] | None = None,
        ) -> str:
            """Run the balance sheet rules engine on a fetched run (synchronous; returns findings).
            The run MUST have status 'fetched' (NormalizationAgent must have called bs_normalize_data +
            wait_for_balance_sheet_review first). If the run is already 'done', returns existing findings.
            Pass rule_ids to evaluate only a specific subset of rules (e.g. ['BS-CASH-BALANCE']).
            Omit rule_ids to run all rules.
            This is the ONLY tool RulesAgent should call — do not call get_balance_sheet_review.
            """
            try:
                payload = _request_json(
                    "POST",
                    f"/api/reviews/balance-sheet/{run_id}/run-rules",
                    json={"rule_ids": rule_ids},
                )
                details = _summarize_run(payload)
                return format_success_response("Balance Sheet Rules Executed", details)
            except Exception as e:
                return format_error_response(str(e), context="running balance sheet rules")

        @mcp.tool(tags={self.domain.value})
        def bs_get_findings(run_id: str) -> str:
            """Get rule findings for a completed balance sheet review run.
            Returns findings, balance_sheet_rows, totals, hitl_requests, artifact_keys.
            Call this ONLY after bs_run_rules has completed (status should be 'done').
            ReportAgent and HITLAgent use this — do not call get_balance_sheet_review.
            """
            try:
                payload = _request_json("GET", f"/api/reviews/balance-sheet/runs/{run_id}")
                details = _summarize_run(payload)
                return format_success_response("Balance Sheet Findings", details)
            except Exception as e:
                return format_error_response(str(e), context="fetching balance sheet findings")

        @mcp.tool(tags={self.domain.value})
        def bs_submit_evidence_request(
            run_id: str,
            rule_id: str,
            evidence_type: str,
            description: str,
            suggested_source: str = "Drive",
        ) -> str:
            """Submit a Human-in-the-Loop (HITL) evidence request for a balance sheet run.
            Use when bs_get_findings shows hitl_requests entries indicating missing external evidence
            (e.g. bank statement, signed loan agreement) that QBO cannot provide automatically.
            HITLAgent is the ONLY agent that should call this tool.
            """
            try:
                payload = _request_json(
                    "POST",
                    f"/api/reviews/balance-sheet/{run_id}/evidence",
                    json={
                        "rule_id": rule_id,
                        "evidence_type": evidence_type,
                        "description": description,
                        "suggested_source": suggested_source,
                    },
                )
                details = {
                    "run_id": payload.get("run_id"),
                    "evidence_submitted": payload.get("evidence_submitted"),
                    "evidence_type": payload.get("evidence_type"),
                    "rule_id": payload.get("rule_id"),
                }
                return format_success_response("Evidence Request Submitted", details)
            except Exception as e:
                return format_error_response(str(e), context="submitting evidence request")

        # -------------------------------------------------------------------
        # Evidence Ledger tools
        # -------------------------------------------------------------------

        @mcp.tool(tags={self.domain.value})
        def log_evidence_entry(
            run_id: str,
            step_type: str,
            content: str,
            tool_name: str | None = None,
            tool_input_summary: str | None = None,
            tool_output_summary: str | None = None,
            confidence: float | None = None,
            parent_entry_id: str | None = None,
        ) -> str:
            """Log a reasoning step to the evidence ledger for a balance sheet review run.
            Used by the AccountingAgent to record hypotheses, tool calls, evidence,
            conclusions, and escalations during investigation.
            step_type must be one of: hypothesis, tool_call, evidence, conclusion, escalation, correction_applied.
            """
            try:
                body: dict = {
                    "step_type": step_type,
                    "content": content,
                }
                if tool_name is not None:
                    body["tool_name"] = tool_name
                if tool_input_summary is not None:
                    body["tool_input_summary"] = tool_input_summary
                if tool_output_summary is not None:
                    body["tool_output_summary"] = tool_output_summary
                if confidence is not None:
                    body["confidence"] = confidence
                if parent_entry_id is not None:
                    body["parent_entry_id"] = parent_entry_id

                payload = _request_json(
                    "POST",
                    f"/api/reviews/balance-sheet/{run_id}/evidence-ledger",
                    json=body,
                )
                return format_success_response("Evidence Entry Logged", payload)
            except Exception as e:
                return format_error_response(str(e), context="logging evidence entry")

        @mcp.tool(tags={self.domain.value})
        def get_evidence_ledger(run_id: str) -> str:
            """Retrieve the full evidence ledger (audit trail) for a review run.
            Returns all reasoning steps: hypotheses, tool calls, evidence, conclusions, escalations.
            """
            try:
                payload = _request_json(
                    "GET",
                    f"/api/reviews/balance-sheet/{run_id}/evidence-ledger",
                )
                return format_success_response("Evidence Ledger", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving evidence ledger")

        @mcp.tool(tags={self.domain.value})
        def get_evidence_summary(run_id: str) -> str:
            """Get a summarized evidence ledger (conclusions and escalations only) for a review run.
            Useful for quick overview of investigation outcomes without full audit trail detail.
            """
            try:
                payload = _request_json(
                    "GET",
                    f"/api/reviews/balance-sheet/{run_id}/evidence-ledger?summary=true",
                )
                return format_success_response("Evidence Summary", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving evidence summary")

        # -------------------------------------------------------------------
        # Correction Memory tools
        # -------------------------------------------------------------------

        @mcp.tool(tags={self.domain.value})
        def store_correction(
            client_id: str,
            user_correction: str,
            correction_type: str,
            rule_id: str | None = None,
            account_ref: str | None = None,
            original_output: str = "",
            reasoning: str = "",
        ) -> str:
            """Store a user correction for a specific client. Corrections are retrieved
            automatically in future reviews to provide context. Types: classification,
            threshold, ignore, procedure, general."""
            try:
                body: dict = {
                    "client_id": client_id,
                    "user_correction": user_correction,
                    "correction_type": correction_type,
                }
                if rule_id is not None:
                    body["rule_id"] = rule_id
                if account_ref is not None:
                    body["account_ref"] = account_ref
                if original_output:
                    body["original_output"] = original_output
                if reasoning:
                    body["reasoning"] = reasoning

                payload = _request_json("POST", "/api/reviews/corrections", json=body)
                return format_success_response("Correction Stored", payload)
            except Exception as e:
                return format_error_response(str(e), context="storing correction")

        @mcp.tool(tags={self.domain.value})
        def retrieve_corrections(
            client_id: str,
            rule_id: str | None = None,
            max_results: int = 5,
        ) -> str:
            """Retrieve stored corrections for a client. Used before generating
            explanations to incorporate prior feedback. Call this as the FIRST step
            of any review workflow to load client context."""
            try:
                params = f"client_id={quote(client_id)}&max_results={max_results}"
                if rule_id:
                    params += f"&rule_id={quote(rule_id)}"
                payload = _request_json("GET", f"/api/reviews/corrections?{params}")
                return format_success_response("Corrections Retrieved", payload)
            except Exception as e:
                return format_error_response(str(e), context="retrieving corrections")

        @mcp.tool(tags={self.domain.value})
        def deactivate_correction(correction_id: str) -> str:
            """Deactivate a correction that is no longer applicable.
            This soft-deletes the correction so it won't appear in future reviews."""
            try:
                payload = _request_json(
                    "DELETE",
                    f"/api/reviews/corrections/{quote(correction_id)}",
                )
                return format_success_response("Correction Deactivated", payload)
            except Exception as e:
                return format_error_response(str(e), context="deactivating correction")

    @property
    def tool_count(self) -> int:
        return 39
