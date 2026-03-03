from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from auth.auth_utils import get_authenticated_user_details, is_easyauth_enabled
from common.client_id import load_client_aliases, resolve_client_id, suggest_client_ids
from common.database.review_store import (
    create_balance_sheet_run,
    find_latest_balance_sheet_run_for_period,
    get_balance_sheet_run,
    update_balance_sheet_run,
)
from common.models.reviews import BalanceSheetRunRecord, MissingEvidenceRequest
from common.rules_engine.config import ClientRulesConfig
from common.rules_engine.context import RuleContext
from common.rules_engine.evidence_requirements import resolve_rule_evidence_requirements
from common.rules_engine.models import RuleRunReport, RuleStatus
from common.rules_engine.registry import registry
from common.rules_engine.runner import RulesRunner
from common.telemetry import current_trace_id, traced_phase
from connectors.qbo.client_store import get_qbo_client_record, list_qbo_client_ids
from connectors.qbo.config import get_client_store_mode
from connectors.drive.config import get_drive_manifest_file_id, is_drive_evidence_enabled
from pipelines.balance_sheet_view import build_balance_sheet_view
from pipelines.data_source import ReviewInputs
from pipelines.live_qbo import LiveQBODataSource
from pipelines.snapshots import (
    BlobRunArtifactStore,
    BlobSnapshotStore,
    MultiRunArtifactStore,
    MultiSnapshotStore,
    RunSnapshotStore,
    build_run_artifact_blob_key,
    build_snapshot_blob_key,
    default_local_run_artifact_store,
    default_local_snapshot_store,
)
from pipelines.summary import generate_balance_sheet_summary

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

DRIVE_ONLY_RULE_IDS = {
    "BS-INVESTMENT-BALANCE-MATCH",
    "BS-LOAN-BALANCE-MATCH",
    "BS-PETTY-CASH-MATCH",
    "BS-WORKING-PAPER-RECONCILES",
}
_BLOB_STORAGE_CONTAINER = "snapshots"
_TEXT_ARTIFACT_EXTENSIONS = {".txt", ".csv", ".md", ".markdown", ".json", ".log"}


class BalanceSheetRunRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    period_end: date
    notes: str | None = None


class BalanceSheetRunResponse(BaseModel):
    run_id: str
    status: str
    # Populated only when ?await=true: full run record fields
    summary: str | None = None
    findings: list | None = None
    balance_sheet_view: dict | None = None
    totals: dict | None = None
    hitl_requests: list | None = None
    artifact_keys: dict | None = None
    snapshot_keys: dict | None = None
    error: str | None = None


class BalanceSheetFetchRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    period_end: date
    notes: str | None = None


class RunRulesRequest(BaseModel):
    rule_ids: list[str] | None = None


class SubmitEvidenceRequest(BaseModel):
    rule_id: str
    evidence_type: str
    description: str
    suggested_source: str = "Drive"


def _authenticated_user_id(http_request: Request) -> str | None:
    authenticated_user = get_authenticated_user_details(request_headers=http_request.headers)
    user_id = str(authenticated_user.get("user_principal_id") or "").strip()
    if is_easyauth_enabled() and not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id or None


@router.post("/balance-sheet/run", response_model=BalanceSheetRunResponse)
async def run_balance_sheet_review(
    request: BalanceSheetRunRequest,
    http_request: Request,
    await_result: bool = Query(False, alias="await"),
):
    user_principal_id = _authenticated_user_id(http_request)

    resolved_client_id = _resolve_client_id(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    _require_qbo_connection_http(
        resolved_client_id,
        user_principal_id=user_principal_id,
    )

    run_id = uuid.uuid4().hex
    await run_in_threadpool(
        create_balance_sheet_run,
        run_id=run_id,
        user_principal_id=user_principal_id,
        client_id=resolved_client_id,
        period_end=request.period_end,
        status="queued",
        notes=request.notes,
    )

    if await_result:
        # Synchronous path: run the full pipeline inline and return complete results.
        # HTTP timeout on Azure Container Apps is 240s; target pipeline is 25-45s.
        try:
            await run_in_threadpool(
                _run_balance_sheet_review_sync,
                run_id=run_id,
                client_id=resolved_client_id,
                period_end=request.period_end,
                notes=request.notes,
                user_principal_id=user_principal_id,
            )
        except Exception as exc:
            LOGGER.exception("Synchronous balance sheet review failed run_id=%s", run_id)
            # Return the failed run record so the caller sees the error details
            record = await run_in_threadpool(
                get_balance_sheet_run, run_id, user_principal_id=user_principal_id
            )
            if record is not None:
                resp = _run_record_response(record)
                return BalanceSheetRunResponse(
                    run_id=record.run_id,
                    status=record.status,
                    error=resp.get("error") or str(exc),
                )
            raise HTTPException(status_code=500, detail=str(exc))

        record = await run_in_threadpool(
            get_balance_sheet_run, run_id, user_principal_id=user_principal_id
        )
        if record is None:
            raise HTTPException(status_code=500, detail="Run record missing after pipeline completion")
        resp = _run_record_response(record)
        return BalanceSheetRunResponse(
            run_id=record.run_id,
            status=record.status,
            summary=resp.get("summary"),
            findings=resp.get("findings"),
            balance_sheet_view=resp.get("balance_sheet_view"),
            totals=resp.get("totals"),
            hitl_requests=resp.get("hitl_requests"),
            artifact_keys=resp.get("artifact_keys"),
            snapshot_keys=resp.get("snapshot_keys"),
            error=resp.get("error"),
        )

    # Async path (default): fire-and-forget, return run_id immediately.
    asyncio.create_task(
        _run_balance_sheet_review_async(
            run_id=run_id,
            client_id=resolved_client_id,
            period_end=request.period_end,
            notes=request.notes,
            user_principal_id=user_principal_id,
        )
    )

    return BalanceSheetRunResponse(run_id=run_id, status="queued")


@router.get("/balance-sheet/runs/{run_id}")
async def get_balance_sheet_review(run_id: str, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)
    record = await run_in_threadpool(
        get_balance_sheet_run,
        run_id,
        user_principal_id=user_principal_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return _run_record_response(record)


@router.get("/balance-sheet/find")
async def find_active_balance_sheet_review(
    client_id: str,
    period_end: date,
    http_request: Request,
):
    """
    Return the most-recent non-failed run for (client_id, period_end).

    Used by the MCP `get_or_create_balance_sheet_review` tool so that orchestrator
    retries and replans reuse the same run_id instead of spawning duplicates.
    Returns 404 when no active run exists (caller should then POST to /run).
    """
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id = _resolve_client_id(
        client_id,
        user_principal_id=user_principal_id,
    )
    record = await run_in_threadpool(
        find_latest_balance_sheet_run_for_period,
        resolved_client_id,
        period_end,
        user_principal_id=user_principal_id,
        exclude_failed=True,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="No active run found")
    return _run_record_response(record)


@router.get("/balance-sheet/runs/{run_id}/snapshots")
async def list_balance_sheet_run_snapshots(run_id: str, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)
    record = await run_in_threadpool(
        get_balance_sheet_run,
        run_id,
        user_principal_id=user_principal_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    snapshot_keys = dict(record.snapshot_keys or {})
    artifact_keys = dict(record.artifact_keys or {})
    return {
        "run_id": run_id,
        "client_id": record.client_id,
        "period_end": record.period_end.isoformat(),
        "status": record.status,
        "snapshot_count": len(snapshot_keys),
        "artifact_count": len(artifact_keys),
        "snapshot_keys": snapshot_keys,
        "artifact_keys": artifact_keys,
    }


@router.get("/snapshots/content")
async def get_snapshot_content(snapshot_key: str, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)

    normalized_key = _normalize_storage_key(snapshot_key, expected_prefix="snapshots")
    await _authorize_storage_key_access(
        storage_key=normalized_key,
        user_principal_id=user_principal_id,
        kind="snapshot",
    )
    content, content_type, source = await run_in_threadpool(_read_storage_key, normalized_key)
    try:
        payload = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Snapshot at '{normalized_key}' is not valid JSON.",
        ) from exc

    return {
        "snapshot_key": normalized_key,
        "content_type": content_type or "application/json",
        "source": source,
        "size_bytes": len(content),
        "snapshot": payload,
    }


@router.get("/artifacts/content")
async def get_artifact_content(artifact_key: str, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)

    normalized_key = _normalize_storage_key(artifact_key, expected_prefix="runs")
    await _authorize_storage_key_access(
        storage_key=normalized_key,
        user_principal_id=user_principal_id,
        kind="artifact",
    )
    content, content_type, source = await run_in_threadpool(_read_storage_key, normalized_key)
    decoded = _decode_artifact_content(
        key=normalized_key,
        content=content,
        content_type=content_type,
    )

    response = {
        "artifact_key": normalized_key,
        "content_type": content_type or _guess_content_type(normalized_key),
        "source": source,
        "size_bytes": len(content),
    }
    response.update(decoded)
    return response


@router.get("/rules")
async def list_balance_sheet_rules(http_request: Request):
    """List all available balance sheet rules with their IDs and titles."""
    _authenticated_user_id(http_request)
    rules = []
    for rule_id in registry.ids():
        try:
            rule_cls = registry.get(rule_id)
            rules.append({
                "rule_id": rule_id,
                "title": getattr(rule_cls, "rule_title", rule_id),
                "best_practices_reference": getattr(rule_cls, "best_practices_reference", ""),
                "sources": list(getattr(rule_cls, "sources", []) or []),
            })
        except Exception:
            rules.append({"rule_id": rule_id, "title": rule_id})
    return {"rules": rules, "count": len(rules)}


@router.post("/balance-sheet/fetch", response_model=BalanceSheetRunResponse)
async def start_balance_sheet_fetch(request: BalanceSheetFetchRequest, http_request: Request):
    """Start a raw-fetch-only run (QBO API calls only; does NOT normalize or run rules).
    Sets status='raw' when complete. NormalizationAgent must call POST /balance-sheet/{run_id}/normalize
    to run normalization (which sets status='fetched').
    RulesAgent must then call POST /balance-sheet/{run_id}/run-rules.
    """
    user_principal_id = _authenticated_user_id(http_request)
    resolved_client_id = _resolve_client_id(request.client_id, user_principal_id=user_principal_id)
    _require_qbo_connection_http(resolved_client_id, user_principal_id=user_principal_id)

    run_id = uuid.uuid4().hex
    await run_in_threadpool(
        create_balance_sheet_run,
        run_id=run_id,
        user_principal_id=user_principal_id,
        client_id=resolved_client_id,
        period_end=request.period_end,
        status="queued",
        notes=request.notes,
    )

    asyncio.create_task(
        _run_balance_sheet_fetch_async(
            run_id=run_id,
            client_id=resolved_client_id,
            period_end=request.period_end,
            notes=request.notes,
            user_principal_id=user_principal_id,
        )
    )

    return BalanceSheetRunResponse(run_id=run_id, status="queued")


@router.post("/balance-sheet/{run_id}/normalize")
async def normalize_balance_sheet_run(run_id: str, http_request: Request):
    """Run the normalization phase on a raw-fetched balance sheet run (synchronous).
    The run must have status 'raw' (i.e. ConnectorAgent called /fetch and it completed).
    Sets status='fetched' when done. RulesAgent can then call /run-rules.
    If the run is already 'fetched' or 'done', returns immediately (idempotent).
    """
    user_principal_id = _authenticated_user_id(http_request)
    record = await run_in_threadpool(get_balance_sheet_run, run_id, user_principal_id=user_principal_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.status == "running":
        raise HTTPException(status_code=409, detail="Run is still in progress. Wait and retry.")
    if record.status == "failed":
        raise HTTPException(status_code=409, detail="Run has failed. Start a new fetch first.")
    if record.status in ("fetched", "done"):
        # Already normalized — idempotent
        return _run_record_response(record)
    if record.status == "queued":
        raise HTTPException(status_code=409, detail="Fetch has not started yet. Call /fetch first.")

    await run_in_threadpool(
        _run_normalize_phase_sync,
        run_id=run_id,
        user_principal_id=user_principal_id,
    )

    record = await run_in_threadpool(get_balance_sheet_run, run_id, user_principal_id=user_principal_id)
    return _run_record_response(record)


@router.post("/balance-sheet/{run_id}/run-rules")
async def run_rules_for_review(run_id: str, request: RunRulesRequest, http_request: Request):
    """Run the rules engine on a fetched balance sheet run (synchronous; returns findings when done).
    The run must have status 'fetched' (i.e. NormalizationAgent called /normalize and it completed).
    Optionally pass rule_ids to evaluate only a specific subset of rules.
    If the run is already 'done', returns existing findings without re-running.
    """
    user_principal_id = _authenticated_user_id(http_request)
    record = await run_in_threadpool(get_balance_sheet_run, run_id, user_principal_id=user_principal_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.status == "running":
        raise HTTPException(status_code=409, detail="Run is still in progress. Wait and retry.")
    if record.status == "failed":
        raise HTTPException(status_code=409, detail="Run has failed. Start a new fetch first.")
    if record.status == "queued":
        raise HTTPException(status_code=409, detail="Run has not started yet. Wait and retry.")
    if record.status == "raw":
        raise HTTPException(status_code=409, detail="Run has not been normalized yet. Call /normalize first.")
    if record.status == "done":
        # Already complete — return existing findings (idempotent)
        return _run_record_response(record)

    rule_ids_set = set(request.rule_ids) if request.rule_ids else None
    await run_in_threadpool(
        _run_rules_phase_sync,
        run_id=run_id,
        user_principal_id=user_principal_id,
        rule_ids=rule_ids_set,
    )

    record = await run_in_threadpool(get_balance_sheet_run, run_id, user_principal_id=user_principal_id)
    return _run_record_response(record)


@router.post("/balance-sheet/{run_id}/evidence")
async def submit_evidence_request(run_id: str, request: SubmitEvidenceRequest, http_request: Request):
    """Append a Human-in-the-Loop evidence request to an existing balance sheet run."""
    user_principal_id = _authenticated_user_id(http_request)
    record = await run_in_threadpool(get_balance_sheet_run, run_id, user_principal_id=user_principal_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    evidence_req = MissingEvidenceRequest(
        rule_id=request.rule_id,
        evidence_type=request.evidence_type,
        description=request.description,
        suggested_source=request.suggested_source,
    )
    # Dedup by (rule_id, evidence_type)
    existing_keys = {(r.rule_id, r.evidence_type) for r in record.hitl_requests}
    if (request.rule_id, request.evidence_type) not in existing_keys:
        record.hitl_requests.append(evidence_req)
        await run_in_threadpool(update_balance_sheet_run, record)

    return {
        "run_id": run_id,
        "evidence_submitted": True,
        "evidence_type": request.evidence_type,
        "rule_id": request.rule_id,
    }


async def _run_balance_sheet_fetch_async(
    *,
    run_id: str,
    client_id: str,
    period_end: date,
    notes: str | None,
    user_principal_id: str | None,
) -> None:
    await run_in_threadpool(
        _run_balance_sheet_fetch_sync,
        run_id=run_id,
        client_id=client_id,
        period_end=period_end,
        notes=notes,
        user_principal_id=user_principal_id,
    )


async def _run_balance_sheet_review_async(
    *,
    run_id: str,
    client_id: str,
    period_end: date,
    notes: str | None,
    user_principal_id: str | None,
) -> None:
    await run_in_threadpool(
        _run_balance_sheet_review_sync,
        run_id=run_id,
        client_id=client_id,
        period_end=period_end,
        notes=notes,
        user_principal_id=user_principal_id,
    )


def _run_balance_sheet_review_sync(
    *,
    run_id: str,
    client_id: str,
    period_end: date,
    notes: str | None,
    user_principal_id: str | None,
) -> None:
    """Full pipeline (backward-compatible monolith): raw fetch + normalize + rules in one shot."""
    _run_balance_sheet_fetch_sync(
        run_id=run_id,
        client_id=client_id,
        period_end=period_end,
        notes=notes,
        user_principal_id=user_principal_id,
    )
    _run_normalize_phase_sync(
        run_id=run_id,
        user_principal_id=user_principal_id,
    )
    _run_rules_phase_sync(
        run_id=run_id,
        user_principal_id=user_principal_id,
    )


def _run_balance_sheet_fetch_sync(
    *,
    run_id: str,
    client_id: str,
    period_end: date,
    notes: str | None,
    user_principal_id: str | None,
) -> None:
    """Phase 1: raw QBO API fetch only. Sets run status to 'raw'.
    Stores raw_qbo_inputs artifact (all raw payloads as JSON) so NormalizationAgent
    can load it via _run_normalize_phase_sync.
    """
    client_id = _resolve_client_id(client_id, user_principal_id=user_principal_id)
    started_ts = datetime.now(timezone.utc)
    LOGGER.info(
        "balance_sheet_fetch_start run_id=%s client_id=%s period_end=%s trace_id=%s",
        run_id, client_id, period_end, current_trace_id(),
    )
    record = get_balance_sheet_run(run_id, user_principal_id=user_principal_id)
    if record is None:
        record = create_balance_sheet_run(
            run_id=run_id,
            user_principal_id=user_principal_id,
            client_id=client_id,
            period_end=period_end,
            status="running",
            notes=notes,
        )
    record.status = "running"
    record.started_at = datetime.now(timezone.utc)
    update_balance_sheet_run(record)

    try:
        with traced_phase(
            "balance_sheet.team_assembly",
            logger=LOGGER,
            attributes={"run.id": run_id, "client.id": client_id},
        ):
            _require_qbo_connection_sync(client_id, user_principal_id=user_principal_id)
            snapshot_store = _build_snapshot_store(run_id)
            artifact_store = _build_artifact_store()
            data_source = LiveQBODataSource(
                snapshot_store=snapshot_store,
                user_principal_id=user_principal_id,
            )

        raw_inputs = data_source.fetch_raw_data(client_id=client_id, period_end=period_end)

        # Persist raw payloads so NormalizationAgent can load them via _run_normalize_phase_sync
        artifact_store.save_json(
            client_id=client_id,
            period_end=period_end,
            run_id=run_id,
            name="raw_qbo_inputs",
            payload=raw_inputs,
        )

        snapshot_keys = _build_snapshot_keys(client_id, period_end, run_id, user_principal_id=user_principal_id)
        artifact_keys = {
            "raw_qbo_inputs": build_run_artifact_blob_key(
                client_id=client_id, period_end=period_end, run_id=run_id,
                name="raw_qbo_inputs", extension="json",
            ),
        }

        record.status = "raw"
        record.snapshot_keys = snapshot_keys
        record.artifact_keys = artifact_keys
        update_balance_sheet_run(record)
        LOGGER.info(
            "balance_sheet_fetch_raw_done run_id=%s duration_ms=%.2f trace_id=%s",
            run_id,
            (datetime.now(timezone.utc) - started_ts).total_seconds() * 1000,
            current_trace_id(),
        )

    except Exception as exc:
        LOGGER.exception("Balance sheet fetch failed for run %s", run_id)
        record.status = "failed"
        record.completed_at = datetime.now(timezone.utc)
        record.error = str(exc)
        update_balance_sheet_run(record)
        raise


def _run_normalize_phase_sync(
    *,
    run_id: str,
    user_principal_id: str | None,
) -> None:
    """Phase 2: normalize raw QBO data into ReviewInputs. Sets run status to 'fetched'.
    Loads the raw_qbo_inputs artifact saved by _run_balance_sheet_fetch_sync,
    runs build_qbo_snapshots + evidence builders, and persists review_inputs artifact.
    Requires that _run_balance_sheet_fetch_sync has already been called (status='raw').
    """
    record = get_balance_sheet_run(run_id, user_principal_id=user_principal_id)
    if record is None:
        raise ValueError(f"Run {run_id} not found")

    client_id = record.client_id
    period_end = record.period_end

    record.status = "running"
    update_balance_sheet_run(record)

    started_ts = datetime.now(timezone.utc)
    try:
        artifact_store = _build_artifact_store()

        # Load raw payloads saved by fetch phase
        raw_key = build_run_artifact_blob_key(
            client_id=client_id, period_end=period_end, run_id=run_id,
            name="raw_qbo_inputs", extension="json",
        )
        raw_bytes, _, _ = _read_storage_key(raw_key)
        raw_inputs = json.loads(raw_bytes.decode("utf-8"))

        snapshot_store = _build_snapshot_store(run_id)
        data_source = LiveQBODataSource(
            snapshot_store=snapshot_store,
            user_principal_id=user_principal_id,
        )
        inputs = data_source.normalize_raw_data(raw=raw_inputs)

        # Serialize and persist ReviewInputs so RulesAgent can load it via _run_rules_phase_sync
        inputs_payload = _serialize_review_inputs(inputs)
        artifact_store.save_json(
            client_id=client_id,
            period_end=period_end,
            run_id=run_id,
            name="review_inputs",
            payload=inputs_payload,
        )

        existing_artifact_keys = dict(record.artifact_keys or {})
        existing_artifact_keys["review_inputs"] = build_run_artifact_blob_key(
            client_id=client_id, period_end=period_end, run_id=run_id,
            name="review_inputs", extension="json",
        )

        record.status = "fetched"
        record.artifact_keys = existing_artifact_keys
        update_balance_sheet_run(record)
        LOGGER.info(
            "balance_sheet_normalize_done run_id=%s duration_ms=%.2f trace_id=%s",
            run_id,
            (datetime.now(timezone.utc) - started_ts).total_seconds() * 1000,
            current_trace_id(),
        )

    except Exception as exc:
        LOGGER.exception("Normalization phase failed for run %s", run_id)
        record.status = "failed"
        record.completed_at = datetime.now(timezone.utc)
        record.error = str(exc)
        update_balance_sheet_run(record)
        raise


def _run_rules_phase_sync(
    *,
    run_id: str,
    user_principal_id: str | None,
    rule_ids: set[str] | None = None,
) -> None:
    """Phase 2: load stored ReviewInputs and run rules. Sets run status to 'done'.
    Requires that _run_balance_sheet_fetch_sync has already been called for this run_id.
    """
    record = get_balance_sheet_run(run_id, user_principal_id=user_principal_id)
    if record is None:
        raise ValueError(f"Run {run_id} not found")

    client_id = record.client_id
    period_end = record.period_end
    notes = record.notes

    record.status = "running"
    update_balance_sheet_run(record)

    started_ts = datetime.now(timezone.utc)
    try:
        artifact_store = _build_artifact_store()
        client_rules = _build_client_rules_config(client_id=client_id, user_principal_id=user_principal_id)

        # Load stored ReviewInputs
        inputs_key = build_run_artifact_blob_key(
            client_id=client_id, period_end=period_end, run_id=run_id,
            name="review_inputs", extension="json",
        )
        inputs_bytes, _, _ = _read_storage_key(inputs_key)
        inputs_data = json.loads(inputs_bytes.decode("utf-8"))
        inputs = _deserialize_review_inputs(inputs_data)

        with traced_phase(
            "balance_sheet.rules",
            logger=LOGGER,
            attributes={"run.id": run_id, "client.id": client_id},
        ):
            report = _run_rules(inputs, client_rules, run_id, rule_ids=rule_ids)

        findings_payload = [res.model_dump(mode="json") for res in report.results]
        report_payload = report.model_dump(mode="json")

        with traced_phase(
            "balance_sheet.report",
            logger=LOGGER,
            attributes={"run.id": run_id, "client.id": client_id},
        ):
            balance_sheet_view = build_balance_sheet_view(
                client_id=client_id, period_end=period_end,
                balance_sheet=inputs.balance_sheet,
                prior_balance_sheets=inputs.prior_balance_sheets,
                results=report.results,
            )
            summary = generate_balance_sheet_summary(
                client_id=client_id, period_end=period_end,
                report=report, notes=notes, balance_sheet_view=balance_sheet_view,
            )
            # Save all 4 artifacts in parallel — each writes to a distinct blob key.
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=4) as _pool:
                _pool.submit(
                    artifact_store.save_json,
                    client_id=client_id, period_end=period_end, run_id=run_id,
                    name="findings", payload=findings_payload,
                )
                _pool.submit(
                    artifact_store.save_json,
                    client_id=client_id, period_end=period_end, run_id=run_id,
                    name="run_report", payload=report_payload,
                )
                _pool.submit(
                    artifact_store.save_json,
                    client_id=client_id, period_end=period_end, run_id=run_id,
                    name="balance_sheet_view", payload=balance_sheet_view,
                )
                _pool.submit(
                    artifact_store.save_text,
                    client_id=client_id, period_end=period_end, run_id=run_id,
                    name="summary", content=summary,
                )

        existing_artifact_keys = dict(record.artifact_keys or {})
        existing_artifact_keys.update({
            "findings": build_run_artifact_blob_key(
                client_id=client_id, period_end=period_end, run_id=run_id,
                name="findings", extension="json",
            ),
            "run_report": build_run_artifact_blob_key(
                client_id=client_id, period_end=period_end, run_id=run_id,
                name="run_report", extension="json",
            ),
            "summary": build_run_artifact_blob_key(
                client_id=client_id, period_end=period_end, run_id=run_id,
                name="summary", extension="txt",
            ),
            "balance_sheet_view": build_run_artifact_blob_key(
                client_id=client_id, period_end=period_end, run_id=run_id,
                name="balance_sheet_view", extension="json",
            ),
        })

        record.status = "done"
        record.completed_at = datetime.now(timezone.utc)
        record.findings = report.results
        record.totals = _totals_payload(report)
        record.run_report = report_payload
        record.summary = summary
        record.balance_sheet_view = balance_sheet_view
        record.hitl_requests = _collect_missing_evidence_requests(
            report=report, evidence=inputs.evidence, client_rules=client_rules,
        )
        record.artifact_keys = existing_artifact_keys
        update_balance_sheet_run(record)
        LOGGER.info(
            "balance_sheet_rules_done run_id=%s duration_ms=%.2f trace_id=%s",
            run_id,
            (datetime.now(timezone.utc) - started_ts).total_seconds() * 1000,
            current_trace_id(),
        )

    except Exception as exc:
        LOGGER.exception("Rules phase failed for run %s", run_id)
        record.status = "failed"
        record.completed_at = datetime.now(timezone.utc)
        record.error = str(exc)
        update_balance_sheet_run(record)
        raise


def _serialize_review_inputs(inputs: ReviewInputs) -> dict[str, Any]:
    """Serialize ReviewInputs to a JSON-safe dict for artifact storage."""
    return {
        "period_end": inputs.period_end.isoformat(),
        "balance_sheet": inputs.balance_sheet.model_dump(mode="json"),
        "prior_balance_sheets": [bs.model_dump(mode="json") for bs in inputs.prior_balance_sheets],
        "profit_and_loss": inputs.profit_and_loss.model_dump(mode="json") if inputs.profit_and_loss else None,
        "evidence": inputs.evidence.model_dump(mode="json"),
        "reconciliations": [r.model_dump(mode="json") for r in inputs.reconciliations],
    }


def _deserialize_review_inputs(data: dict[str, Any]) -> ReviewInputs:
    """Reconstruct ReviewInputs from a previously serialized dict."""
    from common.rules_engine.models import (
        BalanceSheetSnapshot,
        EvidenceBundle,
        ProfitAndLossSnapshot,
        ReconciliationSnapshot,
    )
    return ReviewInputs(
        period_end=date.fromisoformat(data["period_end"]),
        balance_sheet=BalanceSheetSnapshot.model_validate(data["balance_sheet"]),
        prior_balance_sheets=tuple(
            BalanceSheetSnapshot.model_validate(bs) for bs in (data.get("prior_balance_sheets") or [])
        ),
        profit_and_loss=(
            ProfitAndLossSnapshot.model_validate(data["profit_and_loss"])
            if data.get("profit_and_loss") else None
        ),
        evidence=EvidenceBundle.model_validate(data["evidence"]),
        reconciliations=tuple(
            ReconciliationSnapshot.model_validate(r) for r in (data.get("reconciliations") or [])
        ),
    )


def _run_rules(
    inputs,
    client_rules: ClientRulesConfig,
    run_id: str,
    rule_ids: set[str] | None = None,
) -> RuleRunReport:
    ctx = RuleContext(
        period_end=inputs.period_end,
        balance_sheet=inputs.balance_sheet,
        prior_balance_sheets=inputs.prior_balance_sheets,
        profit_and_loss=inputs.profit_and_loss,
        evidence=inputs.evidence,
        reconciliations=inputs.reconciliations,
        client_config=client_rules,
    )
    report = RulesRunner().run(ctx, rule_ids=rule_ids)
    return report.model_copy(update={"run_id": run_id})


def _build_client_rules_config(
    *,
    client_id: str,
    user_principal_id: str | None,
) -> ClientRulesConfig:
    if _drive_manifest_configured(client_id, user_principal_id=user_principal_id):
        return ClientRulesConfig(rules={})
    return ClientRulesConfig(
        rules={rule_id: {"enabled": False} for rule_id in DRIVE_ONLY_RULE_IDS}
    )


def _drive_manifest_configured(
    client_id: str,
    *,
    user_principal_id: str | None,
) -> bool:
    if not is_drive_evidence_enabled():
        return False
    file_id = get_drive_manifest_file_id(
        client_id,
        user_principal_id=user_principal_id,
    )
    return bool(str(file_id or "").strip())


def _build_snapshot_store(run_id: str):
    stores = []
    if _allow_local_only():
        stores.append(default_local_snapshot_store())
    try:
        stores.append(BlobSnapshotStore(prefix="snapshots"))
    except RuntimeError as exc:
        if not _allow_local_only():
            raise
        LOGGER.warning("Blob snapshots disabled: %s", exc)
    base_store = MultiSnapshotStore(tuple(stores))
    return RunSnapshotStore(run_id=run_id, store=base_store)


def _build_artifact_store():
    stores = []
    if _allow_local_only():
        stores.append(default_local_run_artifact_store())
    try:
        stores.append(BlobRunArtifactStore(prefix="runs"))
    except RuntimeError as exc:
        if not _allow_local_only():
            raise
        LOGGER.warning("Blob artifacts disabled: %s", exc)
    return MultiRunArtifactStore(tuple(stores))


def _allow_local_only() -> bool:
    if os.getenv("APP_ENV", "").strip().lower() == "dev":
        return True
    if os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT"):
        return False
    return True


def _build_snapshot_keys(
    client_id: str,
    period_end: date,
    run_id: str,
    *,
    user_principal_id: str | None,
) -> dict[str, str]:
    names = _base_snapshot_names()
    names.extend(
        _counterparty_snapshot_names(
            client_id,
            user_principal_id=user_principal_id,
        )
    )
    names.extend(
        _drive_snapshot_names(
            client_id,
            user_principal_id=user_principal_id,
        )
    )
    keys: dict[str, str] = {}
    for name in names:
        keys[name] = build_snapshot_blob_key(
            client_id=client_id,
            period_end=period_end,
            run_id=run_id,
            name=name,
        )
    return keys


def _base_snapshot_names() -> list[str]:
    return [
        "qbo_balance_sheet",
        "qbo_profit_and_loss",
        "qbo_trial_balance",
        "qbo_accounts",
        "qbo_aged_payables_summary",
        "qbo_aged_payables_detail",
        "qbo_aged_receivables_summary",
        "qbo_aged_receivables_detail",
        "qbo_tax_agencies",
        "qbo_tax_returns",
        "qbo_tax_payments",
    ]


def _counterparty_snapshot_names(
    client_id: str,
    *,
    user_principal_id: str | None,
) -> list[str]:
    counterparties: Iterable[dict[str, Any]] = []
    if get_client_store_mode() == "cosmos":
        record = get_qbo_client_record(
            client_id,
            user_principal_id=user_principal_id,
        )
        if record:
            counterparties = record.get("counterparties", []) or []
    else:
        counterparties = _load_counterparties_from_file(client_id)

    names: list[str] = []
    for cp in counterparties:
        if not isinstance(cp, dict):
            continue
        name = str(cp.get("name") or cp.get("realm_id") or "").strip()
        if not name:
            continue
        names.append(f"qbo_balance_sheet_counterparty_{_safe_slug(name)}")
    return names


def _drive_snapshot_names(
    client_id: str,
    *,
    user_principal_id: str | None,
) -> list[str]:
    if not is_drive_evidence_enabled():
        return []
    file_id = get_drive_manifest_file_id(
        client_id,
        user_principal_id=user_principal_id,
    )
    if not file_id:
        return []
    return ["drive_evidence_manifest"]


def _load_counterparties_from_file(client_id: str) -> list[dict[str, Any]]:
    path = _client_config_path()
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    entry = (raw.get("clients") or {}).get(client_id)
    if not isinstance(entry, dict):
        return []
    counterparties = entry.get("counterparties") or []
    return [cp for cp in counterparties if isinstance(cp, dict)]


def _load_client_ids_from_file() -> list[str]:
    path = _client_config_path()
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    clients = raw.get("clients") or {}
    if not isinstance(clients, dict):
        return []
    return [str(key) for key in clients.keys()]


def _client_config_path() -> Path:
    override = os.getenv("CLIENT_CONFIG_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "config" / "clients.json"


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return cleaned or "unknown"


def _known_client_ids(*, user_principal_id: str | None) -> list[str]:
    if get_client_store_mode() == "cosmos":
        try:
            return list_qbo_client_ids(user_principal_id=user_principal_id)
        except Exception:
            return []
    return _load_client_ids_from_file()


def _resolve_client_id(client_id: str, *, user_principal_id: str | None) -> str:
    aliases = load_client_aliases()
    return resolve_client_id(
        client_id,
        _known_client_ids(user_principal_id=user_principal_id),
        aliases,
    )


def _client_id_prompt(client_id: str, *, user_principal_id: str | None) -> str | None:
    suggestions = suggest_client_ids(
        client_id,
        _known_client_ids(user_principal_id=user_principal_id),
    )
    if not suggestions:
        return None
    if len(suggestions) == 1:
        return f"Did you mean '{suggestions[0]}'? If so, retry with that exact client_id."
    joined = ", ".join(f"'{value}'" for value in suggestions)
    return f"Did you mean one of {joined}? If so, retry with the exact client_id."


def _missing_qbo_connection_message(
    client_id: str,
    *,
    user_principal_id: str | None,
) -> str | None:
    if get_client_store_mode() != "cosmos":
        return None
    record = get_qbo_client_record(client_id, user_principal_id=user_principal_id)
    if not record:
        prompt = _client_id_prompt(client_id, user_principal_id=user_principal_id)
        if prompt:
            return (
                f"QBO connection missing for client_id '{client_id}'. "
                f"{prompt} If you intended a new client, call "
                "/api/qbo/connect/start?client_id=... to connect."
            )
        return (
            f"QBO connection missing for client_id '{client_id}'. "
            "Call /api/qbo/connect/start?client_id=... to connect."
        )
    realm_id = str(record.get("realm_id") or "").strip()
    refresh_token = str(record.get("refresh_token") or "").strip()
    if not realm_id or not refresh_token:
        return (
            f"QBO connection incomplete for client_id '{client_id}'. "
            "Call /api/qbo/connect/start?client_id=... to reconnect."
        )
    return None


def _require_qbo_connection_http(
    client_id: str,
    *,
    user_principal_id: str | None,
) -> None:
    message = _missing_qbo_connection_message(
        client_id,
        user_principal_id=user_principal_id,
    )
    if message:
        raise HTTPException(status_code=409, detail=message)


def _require_qbo_connection_sync(
    client_id: str,
    *,
    user_principal_id: str | None,
) -> None:
    message = _missing_qbo_connection_message(
        client_id,
        user_principal_id=user_principal_id,
    )
    if message:
        raise RuntimeError(message)


def _collect_missing_evidence_requests(
    *,
    report: RuleRunReport,
    evidence,
    client_rules: ClientRulesConfig,
) -> list[MissingEvidenceRequest]:
    requests: dict[tuple[str, str], MissingEvidenceRequest] = {}
    for result in report.results:
        if result.status != RuleStatus.NEEDS_REVIEW:
            continue
        rule_cls = None
        try:
            rule_cls = registry.get(result.rule_id)
        except KeyError:
            continue
        config_model = getattr(rule_cls, "config_model", None)
        if config_model is None:
            continue
        cfg = client_rules.get_rule_config(result.rule_id, config_model)
        for requirement in resolve_rule_evidence_requirements(result.rule_id, cfg):
            if evidence.first(requirement.evidence_type) is not None:
                continue
            key = (result.rule_id, requirement.evidence_type)
            if key in requests:
                continue
            requests[key] = MissingEvidenceRequest(
                rule_id=result.rule_id,
                rule_title=result.rule_title,
                evidence_type=requirement.evidence_type,
                description=_missing_description(result, requirement.evidence_type),
                suggested_source=requirement.suggested_source,
                required_document=requirement.required_document,
                adapter_hint=requirement.adapter_hint,
            )
    return list(requests.values())


def _missing_description(result, evidence_type: str) -> str:
    summary = (result.summary or "").strip()
    if summary:
        return summary
    human_action = (result.human_action or "").strip()
    if human_action:
        return human_action
    return f"Missing evidence '{evidence_type}' for {result.rule_title}."


def _totals_payload(report: RuleRunReport) -> dict[str, int]:
    totals: dict[str, int] = {}
    for status, count in report.totals.items():
        key = getattr(status, "value", status)
        totals[str(key)] = int(count)
    return totals


def _run_record_response(record: BalanceSheetRunRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="json")
    payload["run_id"] = payload.pop("id")
    return payload


def _normalize_storage_key(key: str, *, expected_prefix: str) -> str:
    normalized = str(key or "").strip().lstrip("/")
    if not normalized:
        raise HTTPException(status_code=400, detail="storage key is required")
    if not normalized.startswith(f"{expected_prefix}/"):
        raise HTTPException(
            status_code=400,
            detail=f"storage key must start with '{expected_prefix}/'",
        )
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="invalid storage key")
    return normalized


def _extract_run_id_from_storage_key(storage_key: str) -> str:
    parts = [part for part in storage_key.split("/") if part]
    # Expected shape:
    #   snapshots/{client_id}/{period_end}/{run_id}/...
    #   runs/{client_id}/{period_end}/{run_id}/...
    if len(parts) < 5:
        raise HTTPException(
            status_code=400,
            detail="storage key does not include a run_id segment",
        )
    run_id = str(parts[3] or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="invalid run_id in storage key")
    return run_id


async def _authorize_storage_key_access(
    *,
    storage_key: str,
    user_principal_id: str | None,
    kind: str,
) -> None:
    if not user_principal_id:
        # In non-EasyAuth local runs we allow read access for debugging.
        return

    run_id = _extract_run_id_from_storage_key(storage_key)
    record = await run_in_threadpool(
        get_balance_sheet_run,
        run_id,
        user_principal_id=user_principal_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if kind == "snapshot":
        allowed = set((record.snapshot_keys or {}).values())
    else:
        allowed = set((record.artifact_keys or {}).values())
    if storage_key not in allowed:
        raise HTTPException(
            status_code=403,
            detail="Access denied for the provided storage key.",
        )


def _read_storage_key(key: str) -> tuple[bytes, str | None, str]:
    local = _read_local_storage_key(key)
    if local is not None:
        return local

    try:
        blob = _read_blob_storage_key(key)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if blob is not None:
        return blob

    raise HTTPException(status_code=404, detail=f"No content found for key '{key}'.")


def _read_local_storage_key(key: str) -> tuple[bytes, str | None, str] | None:
    try:
        if key.startswith("snapshots/"):
            root = default_local_snapshot_store().root_dir
            relative_key = key[len("snapshots/") :]
        elif key.startswith("runs/"):
            root = default_local_run_artifact_store().root_dir
            relative_key = key[len("runs/") :]
        else:
            return None
    except Exception:
        # Container/runtime layouts may not have a project-root-relative local data dir.
        # In that case, skip local lookup and fall back to blob storage.
        return None

    root_resolved = root.resolve()
    file_path = (root / relative_key).resolve()
    if root_resolved not in file_path.parents and file_path != root_resolved:
        raise HTTPException(status_code=400, detail="invalid storage key path")
    if not file_path.exists() or not file_path.is_file():
        return None

    content = file_path.read_bytes()
    content_type = _guess_content_type(str(file_path))
    return content, content_type, "local"


def _read_blob_storage_key(key: str) -> tuple[bytes, str | None, str] | None:
    try:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise RuntimeError("azure-storage-blob is required to read blob snapshots/artifacts.") from exc

    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    if not account_url:
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "").strip()
        if not account_name:
            raise RuntimeError(
                "AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_ACCOUNT_NAME is required."
            )
        account_url = f"https://{account_name}.blob.core.windows.net"

    try:
        credential = DefaultAzureCredential()
        client = BlobServiceClient(account_url=account_url, credential=credential)
        container = client.get_container_client(_BLOB_STORAGE_CONTAINER)
        blob = container.get_blob_client(key)
        with traced_phase(
            "dependency.blob.download_content",
            logger=LOGGER,
            attributes={"blob.container": _BLOB_STORAGE_CONTAINER, "blob.key": key},
        ):
            downloader = blob.download_blob()
            content = downloader.readall()
    except ResourceNotFoundError:
        return None
    except Exception as exc:
        raise RuntimeError(f"Blob download failed for '{key}': {exc}") from exc

    content_type = None
    try:
        props = blob.get_blob_properties()
        settings = getattr(props, "content_settings", None)
        content_type = getattr(settings, "content_type", None)
    except Exception:
        content_type = None

    return content, content_type, "blob"


def _decode_artifact_content(
    *,
    key: str,
    content: bytes,
    content_type: str | None,
) -> dict[str, Any]:
    suffix = Path(key).suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(content.decode("utf-8"))
            return {"encoding": "json", "artifact": payload}
        except Exception:
            pass

    normalized_type = (content_type or "").strip().lower()
    is_text = suffix in _TEXT_ARTIFACT_EXTENSIONS or normalized_type.startswith("text/")
    if is_text or normalized_type in {"application/json", "application/xml"}:
        text = content.decode("utf-8", errors="replace")
        return {"encoding": "text", "artifact": text}

    return {
        "encoding": "base64",
        "artifact_base64": base64.b64encode(content).decode("ascii"),
    }


def _guess_content_type(path_like: str) -> str:
    guessed, _ = mimetypes.guess_type(path_like)
    if guessed:
        return guessed
    suffix = Path(path_like).suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    if suffix == ".txt":
        return "text/plain"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"
