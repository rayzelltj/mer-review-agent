"""Database factory for creating database instances."""

import asyncio
import logging
from typing import Optional

from common.config.app_config import config

from .cosmosdb import CosmosDBClient
from .database_base import DatabaseBase


class DatabaseFactory:
    """Factory class for creating database instances."""

    _instances: dict[str, DatabaseBase] = {}
    _lock = asyncio.Lock()
    _logger = logging.getLogger(__name__)

    @staticmethod
    async def get_database(
        user_id: str = "",
        force_new: bool = False,
    ) -> DatabaseBase:
        """
        Get a database instance.

        Args:
            endpoint: CosmosDB endpoint URL
            credential: Azure credential for authentication
            database_name: Name of the CosmosDB database
            container_name: Name of the CosmosDB container
            session_id: Session ID for partitioning
            user_id: User ID for data isolation
            force_new: Force creation of new instance

        Returns:
            DatabaseBase: Database instance
        """
        normalized_user_id = str(user_id or "").strip() or "__default__"
        existing = DatabaseFactory._instances.get(normalized_user_id)
        if existing is not None and not force_new:
            return existing

        async with DatabaseFactory._lock:
            existing = DatabaseFactory._instances.get(normalized_user_id)
            if existing is not None and not force_new:
                return existing

            cosmos_db_client = CosmosDBClient(
                endpoint=config.COSMOSDB_ENDPOINT,
                credential=config.get_azure_credentials(),
                database_name=config.COSMOSDB_DATABASE,
                container_name=config.COSMOSDB_CONTAINER,
                session_id="",
                user_id=user_id,
            )

            await cosmos_db_client.initialize()

            if not force_new:
                DatabaseFactory._instances[normalized_user_id] = cosmos_db_client

            return cosmos_db_client

    @staticmethod
    async def close_all():
        """Close all database connections."""
        instances = list(DatabaseFactory._instances.values())
        DatabaseFactory._instances = {}
        for instance in instances:
            try:
                await instance.close()
            except Exception:
                DatabaseFactory._logger.exception(
                    "Error while closing database instance"
                )
