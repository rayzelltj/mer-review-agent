from __future__ import annotations

import os
from typing import Optional

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

_cosmos_client: Optional[CosmosClient] = None
_container_client = None


def get_cosmos_container_client():
    global _cosmos_client, _container_client
    if _container_client is not None:
        return _container_client

    endpoint = os.getenv("COSMOSDB_ENDPOINT", "").strip()
    database_name = os.getenv("COSMOSDB_DATABASE", "").strip()
    container_name = os.getenv("COSMOSDB_CONTAINER", "").strip()
    if not endpoint or not database_name or not container_name:
        raise RuntimeError(
            "COSMOSDB_ENDPOINT, COSMOSDB_DATABASE, and COSMOSDB_CONTAINER are required."
        )

    key = os.getenv("COSMOSDB_KEY", "").strip()
    if key:
        _cosmos_client = CosmosClient(endpoint, credential=key)
    else:
        credential = DefaultAzureCredential()
        _cosmos_client = CosmosClient(endpoint, credential=credential)

    database = _cosmos_client.get_database_client(database_name)
    _container_client = database.get_container_client(container_name)
    return _container_client


def reset_cosmos_container_client() -> None:
    global _cosmos_client, _container_client
    if _cosmos_client:
        try:
            _cosmos_client.close()
        except Exception:
            pass
    _cosmos_client = None
    _container_client = None
