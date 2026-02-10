from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol


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
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name}.json"
        out_path.write_text(json.dumps(payload, indent=2))


class BlobSnapshotStore:
    def __init__(
        self,
        *,
        container_name: str = "snapshots",
        account_url: str | None = None,
    ) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            raise RuntimeError(
                "azure-storage-blob is not installed; cannot enable blob snapshots."
            ) from exc

        account_url = account_url or os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
        if not account_url:
            account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "").strip()
            if not account_name:
                raise RuntimeError(
                    "AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_ACCOUNT_NAME is required for blob snapshots."
                )
            account_url = f"https://{account_name}.blob.core.windows.net"

        credential = DefaultAzureCredential()
        self._client = BlobServiceClient(account_url=account_url, credential=credential)
        self._container = container_name

    def save_json(
        self,
        *,
        client_id: str,
        period_end: date,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        key = f"{client_id}/{period_end.isoformat()}/{name}.json"
        container = self._client.get_container_client(self._container)
        container.upload_blob(
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
