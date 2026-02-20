from __future__ import annotations

import base64
import json
import mimetypes
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from adapters.mock_evidence.evidence_manifest import evidence_bundle_from_manifest
from auth.auth_utils import get_authenticated_user_details, is_easyauth_enabled
from connectors.drive.client import (
    DriveHttpError,
    download_file_bytes,
    get_file_metadata,
    list_files,
)
from connectors.drive.config import build_drive_config


router = APIRouter(prefix="/api/drive", tags=["drive"])

_INLINE_CONTENT_LIMIT = 300_000
_TEXTUAL_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "text/plain",
    "text/csv",
    "text/markdown",
}


class DriveListFilesRequest(BaseModel):
    client_id: str | None = None
    folder_id: str | None = None
    query: str | None = None
    page_size: int = Field(default=100, ge=1, le=1000)


class DriveGetFileRequest(BaseModel):
    client_id: str | None = None
    file_id: str
    export_mime_type: str | None = None
    max_inline_bytes: int = Field(default=_INLINE_CONTENT_LIMIT, ge=1024, le=2_000_000)


class DriveEvidenceManifestRequest(BaseModel):
    client_id: str | None = None
    file_id: str | None = None


def _authenticated_user_id(http_request: Request) -> str | None:
    authenticated_user = get_authenticated_user_details(request_headers=http_request.headers)
    user_id = str(authenticated_user.get("user_principal_id") or "").strip()
    if is_easyauth_enabled() and not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id or None


@router.get("/status")
def drive_status(http_request: Request, client_id: str | None = Query(None)):
    user_principal_id = _authenticated_user_id(http_request)
    try:
        cfg = build_drive_config(
            client_id=client_id,
            user_principal_id=user_principal_id,
        )
    except Exception as exc:
        return {
            "connected": False,
            "reason": str(exc),
            "client_id": client_id,
        }

    folder_accessible = None
    reason = None
    if cfg.root_folder_id:
        try:
            list_files(
                cfg,
                folder_id=cfg.root_folder_id,
                page_size=1,
            )
            folder_accessible = True
        except Exception as exc:
            folder_accessible = False
            reason = str(exc)

    return {
        "connected": reason is None,
        "reason": reason,
        "client_id": cfg.client_record_id or client_id,
        "root_folder_id": cfg.root_folder_id,
        "evidence_manifest_file_id": cfg.evidence_manifest_file_id,
        "folder_accessible": folder_accessible,
        "supports_all_drives": cfg.supports_all_drives,
        "include_items_from_all_drives": cfg.include_items_from_all_drives,
    }


@router.post("/files/list")
def drive_list_files(request: DriveListFilesRequest, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)
    cfg = _build_cfg_or_http_error(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    folder_id = str(request.folder_id or cfg.root_folder_id or "").strip()
    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id is required")
    try:
        files = list_files(
            cfg,
            folder_id=folder_id,
            query=request.query,
            page_size=request.page_size,
        )
    except Exception as exc:
        _raise_http_for_drive_error(exc)
    return {
        "client_id": cfg.client_record_id or request.client_id,
        "folder_id": folder_id,
        "count": len(files),
        "files": files,
    }


@router.post("/files/get")
def drive_get_file(request: DriveGetFileRequest, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)
    cfg = _build_cfg_or_http_error(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    try:
        metadata = get_file_metadata(cfg, file_id=request.file_id)
        content = download_file_bytes(
            cfg,
            file_id=request.file_id,
            export_mime_type=request.export_mime_type,
        )
    except Exception as exc:
        _raise_http_for_drive_error(exc)

    content_type = _resolve_content_type(
        requested_content_type=request.export_mime_type,
        metadata=metadata,
    )

    response: dict[str, Any] = {
        "client_id": cfg.client_record_id or request.client_id,
        "file_id": request.file_id,
        "metadata": metadata,
        "content_type": content_type,
        "size_bytes": len(content),
    }

    if len(content) > request.max_inline_bytes:
        response["content_omitted"] = True
        response["max_inline_bytes"] = request.max_inline_bytes
        return response

    decoded = _decode_content(content=content, content_type=content_type)
    response.update(decoded)
    return response


@router.post("/evidence/manifest")
def drive_get_evidence_manifest(request: DriveEvidenceManifestRequest, http_request: Request):
    user_principal_id = _authenticated_user_id(http_request)
    cfg = _build_cfg_or_http_error(
        request.client_id,
        user_principal_id=user_principal_id,
    )
    file_id = str(request.file_id or cfg.evidence_manifest_file_id or "").strip()
    if not file_id:
        raise HTTPException(
            status_code=400,
            detail="file_id is required (or configure DRIVE_EVIDENCE_MANIFEST_FILE_ID).",
        )

    try:
        raw = download_file_bytes(
            cfg,
            file_id=file_id,
            export_mime_type="application/json",
        )
    except Exception as exc:
        _raise_http_for_drive_error(exc)

    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Drive file '{file_id}' did not contain valid JSON.",
        ) from exc

    try:
        bundle = evidence_bundle_from_manifest(manifest, source_default="google_drive")
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Evidence manifest parse failed: {exc}",
        ) from exc

    items = [item.model_dump(mode="json") for item in bundle.items]
    return {
        "client_id": cfg.client_record_id or request.client_id,
        "file_id": file_id,
        "evidence_count": len(items),
        "evidence_types": sorted({item["evidence_type"] for item in items if item.get("evidence_type")}),
        "manifest": manifest,
        "evidence_items": items,
    }


def _build_cfg_or_http_error(*, client_id: str | None, user_principal_id: str | None):
    try:
        return build_drive_config(
            client_id=client_id,
            user_principal_id=user_principal_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Drive config error: {exc}") from exc


def _raise_http_for_drive_error(exc: Exception) -> None:
    if isinstance(exc, DriveHttpError):
        status = 502
        if exc.status == 401:
            status = 401
        elif exc.status == 404:
            status = 404
        elif exc.status == 403:
            status = 403
        detail = str(exc.body or str(exc))
        raise HTTPException(status_code=status, detail=detail) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resolve_content_type(*, requested_content_type: str | None, metadata: dict[str, Any]) -> str:
    requested = str(requested_content_type or "").strip()
    if requested:
        return requested
    metadata_mime = str(metadata.get("mimeType") or "").strip()
    if metadata_mime and not metadata_mime.startswith("application/vnd.google-apps."):
        return metadata_mime
    name = str(metadata.get("name") or "").strip()
    guessed = mimetypes.guess_type(name)[0]
    if guessed:
        return guessed
    return "application/octet-stream"


def _decode_content(*, content: bytes, content_type: str) -> dict[str, Any]:
    normalized_type = content_type.lower().strip()
    if normalized_type.startswith("text/") or normalized_type in _TEXTUAL_CONTENT_TYPES:
        text = content.decode("utf-8", errors="replace")
        if normalized_type == "application/json":
            try:
                return {"encoding": "json", "content_json": json.loads(text)}
            except Exception:
                return {"encoding": "text", "content_text": text}
        return {"encoding": "text", "content_text": text}
    return {
        "encoding": "base64",
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
