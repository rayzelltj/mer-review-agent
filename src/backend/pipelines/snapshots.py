from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from common.telemetry import traced_phase


LOGGER = logging.getLogger(__name__)


class SnapshotStore(Protocol):
    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        ...


@dataclass(frozen=True)
class LocalSnapshotStore:
    root_dir: Path

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        out_dir = self.root_dir / client_id / period_end.isoformat()
        out_path = out_dir / f"{name}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))


class BlobSnapshotStore:
    def __init__(
        self,
        *,
        container_name: str = "snapshots",
        account_url: str | None = None,
        prefix: str | None = None,
    ) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient
            from azure.core.exceptions import ResourceExistsError
        except ImportError as exc:
            raise RuntimeError(
                "azure-storage-blob is not installed; cannot enable blob snapshots."
            ) from exc

        account_url = (
            account_url
            or os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
            or os.getenv("AZURE_STORAGE_BLOB_URL", "").strip()
        )
        if not account_url:
            account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "").strip()
            if not account_name:
                raise RuntimeError(
                    "AZURE_STORAGE_ACCOUNT_URL, AZURE_STORAGE_BLOB_URL, or "
                    "AZURE_STORAGE_ACCOUNT_NAME is required for blob snapshots."
                )
            account_url = f"https://{account_name}.blob.core.windows.net"

        credential = DefaultAzureCredential()
        self._client = BlobServiceClient(account_url=account_url, credential=credential)
        self._container = container_name
        self._prefix = (prefix or "").strip("/")
        self._container_client = self._client.get_container_client(self._container)
        try:
            self._container_client.create_container()
        except ResourceExistsError:
            pass

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        key = _build_blob_key(
            prefix=self._prefix,
            client_id=client_id,
            period_end=period_end,
            name=name,
            extension="json",
        )
        with traced_phase(
            "dependency.blob.upload_snapshot",
            logger=LOGGER,
            attributes={"blob.container": self._container, "blob.key": key},
        ):
            self._container_client.upload_blob(
                key,
                json.dumps(payload, indent=2),
                overwrite=True,
            )


@dataclass(frozen=True)
class MultiSnapshotStore:
    stores: tuple[SnapshotStore, ...]

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        for store in self.stores:
            store.save_json(
                client_id=client_id,
                period_end=period_end,
                name=name,
                payload=payload,
            )


def default_local_snapshot_store() -> LocalSnapshotStore:
    root = Path(__file__).resolve().parents[3] / "data" / "snapshots"
    return LocalSnapshotStore(root_dir=root)


@dataclass(frozen=True)
class RunSnapshotStore:
    run_id: str
    store: SnapshotStore

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        normalized = _normalize_snapshot_name(name)
        scoped = f"{self.run_id}/{normalized}"
        self.store.save_json(
            client_id=client_id,
            period_end=period_end,
            name=scoped,
            payload=payload,
        )


class RunArtifactStore(Protocol):
    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        ...

    def save_text(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        content: str,
    ) -> None:
        ...


@dataclass(frozen=True)
class LocalRunArtifactStore:
    root_dir: Path

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        out_dir = self.root_dir / client_id / period_end.isoformat() / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name}.json"
        out_path.write_text(json.dumps(payload, indent=2))

    def save_text(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        content: str,
    ) -> None:
        out_dir = self.root_dir / client_id / period_end.isoformat() / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name}.txt"
        out_path.write_text(content)


class BlobRunArtifactStore:
    def __init__(
        self,
        *,
        container_name: str = "snapshots",
        account_url: str | None = None,
        prefix: str | None = None,
    ) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient, ContentSettings
            from azure.core.exceptions import ResourceExistsError
        except ImportError as exc:
            raise RuntimeError(
                "azure-storage-blob is not installed; cannot enable blob artifacts."
            ) from exc

        account_url = (
            account_url
            or os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
            or os.getenv("AZURE_STORAGE_BLOB_URL", "").strip()
        )
        if not account_url:
            account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "").strip()
            if not account_name:
                raise RuntimeError(
                    "AZURE_STORAGE_ACCOUNT_URL, AZURE_STORAGE_BLOB_URL, or "
                    "AZURE_STORAGE_ACCOUNT_NAME is required for blob artifacts."
                )
            account_url = f"https://{account_name}.blob.core.windows.net"

        credential = DefaultAzureCredential()
        self._client = BlobServiceClient(account_url=account_url, credential=credential)
        self._container = container_name
        self._prefix = (prefix or "").strip("/")
        self._container_client = self._client.get_container_client(self._container)
        self._text_settings = ContentSettings(content_type="text/plain")
        try:
            self._container_client.create_container()
        except ResourceExistsError:
            pass

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        key = _build_blob_key(
            prefix=self._prefix,
            client_id=client_id,
            period_end=period_end,
            name=f"{run_id}/{name}",
            extension="json",
        )
        with traced_phase(
            "dependency.blob.upload_artifact_json",
            logger=LOGGER,
            attributes={"blob.container": self._container, "blob.key": key},
        ):
            self._container_client.upload_blob(
                key,
                json.dumps(payload, indent=2),
                overwrite=True,
            )

    def save_text(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        content: str,
    ) -> None:
        key = _build_blob_key(
            prefix=self._prefix,
            client_id=client_id,
            period_end=period_end,
            name=f"{run_id}/{name}",
            extension="txt",
        )
        with traced_phase(
            "dependency.blob.upload_artifact_text",
            logger=LOGGER,
            attributes={"blob.container": self._container, "blob.key": key},
        ):
            self._container_client.upload_blob(
                key,
                content,
                overwrite=True,
                content_settings=self._text_settings,
            )


@dataclass(frozen=True)
class MultiRunArtifactStore:
    stores: tuple[RunArtifactStore, ...]

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        for store in self.stores:
            store.save_json(
                client_id=client_id,
                period_end=period_end,
                run_id=run_id,
                name=name,
                payload=payload,
            )

    def save_text(
        self,
        *,
        client_id: str,
        period_end: date,
        run_id: str,
        name: str,
        content: str,
    ) -> None:
        for store in self.stores:
            store.save_text(
                client_id=client_id,
                period_end=period_end,
                run_id=run_id,
                name=name,
                content=content,
            )


def default_local_run_artifact_store() -> LocalRunArtifactStore:
    root = Path(__file__).resolve().parents[3] / "data" / "runs"
    return LocalRunArtifactStore(root_dir=root)


def _normalize_snapshot_name(name: str) -> str:
    prefix = "qbo_balance_sheet_counterparty_"
    if name.startswith(prefix):
        return "qbo_counterparty_balance_sheet_" + name[len(prefix):]
    return name


def _build_blob_key(
    *,
    prefix: str,
    client_id: str,
    period_end: date,
    name: str,
    extension: str,
) -> str:
    base = f"{client_id}/{period_end.isoformat()}/{name}.{extension}"
    if prefix:
        return f"{prefix}/{base}"
    return base


def build_snapshot_blob_key(
    *,
    client_id: str,
    period_end: date,
    run_id: str,
    name: str,
) -> str:
    normalized = _normalize_snapshot_name(name)
    return _build_blob_key(
        prefix="snapshots",
        client_id=client_id,
        period_end=period_end,
        name=f"{run_id}/{normalized}",
        extension="json",
    )


def build_run_artifact_blob_key(
    *,
    client_id: str,
    period_end: date,
    run_id: str,
    name: str,
    extension: str,
) -> str:
    return _build_blob_key(
        prefix="runs",
        client_id=client_id,
        period_end=period_end,
        name=f"{run_id}/{name}",
        extension=extension,
    )
