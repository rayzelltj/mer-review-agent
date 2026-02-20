from __future__ import annotations

import asyncio
import logging

import aiohttp


logger = logging.getLogger(__name__)


class SharedHttpClientManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._session and not self._session.closed:
                await self._session.close()
                logger.info("Closed shared aiohttp ClientSession")
            self._session = None


_shared_http_client_manager = SharedHttpClientManager()


async def get_shared_aiohttp_session() -> aiohttp.ClientSession:
    return await _shared_http_client_manager.get_session()


async def close_shared_aiohttp_session() -> None:
    await _shared_http_client_manager.close()
