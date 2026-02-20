from typing import Any, Dict, Optional, Union

import aiohttp
from common.config.app_config import config
from common.http_clients import get_shared_aiohttp_session


class BaseAPIService:
    """Minimal async HTTP API service.

    - Reads base endpoints from AppConfig using `from_config` factory.
    - Provides simple GET/POST helpers with JSON payloads.
    - Designed to be subclassed (e.g., MCPService, FoundryService).
    """

    def __init__(
        self,
        base_url: str,
        *,
        default_headers: Optional[Dict[str, str]] = None,
        timeout_seconds: int = 30,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session_external = session is not None
        self._session_shared = False
        self._session: Optional[aiohttp.ClientSession] = session

    @classmethod
    def from_config(
        cls,
        endpoint_attr: str,
        *,
        default: Optional[str] = None,
        **kwargs: Any,
    ) -> "BaseAPIService":
        """Create a service using an endpoint attribute from AppConfig.

        Args:
            endpoint_attr: Name of the attribute on AppConfig (e.g., 'AZURE_AI_AGENT_ENDPOINT').
            default: Optional default if attribute missing or empty.
            **kwargs: Passed through to the constructor.
        """
        base_url = getattr(config, endpoint_attr, None) or default
        if not base_url:
            raise ValueError(
                f"Endpoint '{endpoint_attr}' not configured in AppConfig and no default provided"
            )
        return cls(base_url, **kwargs)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            if self._session_external:
                raise RuntimeError(
                    "External aiohttp session was expected but is not available."
                )
            self._session = await get_shared_aiohttp_session()
            self._session_shared = True
        elif self._session.closed:
            if self._session_external:
                raise RuntimeError("External aiohttp session is closed.")
            self._session = await get_shared_aiohttp_session()
            self._session_shared = True
        return self._session

    def _url(self, path: str) -> str:
        path = path or ""
        if not path:
            return self.base_url
        return f"{self.base_url}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str = "",
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Union[str, int, float]]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        session = await self._ensure_session()
        url = self._url(path)
        merged_headers = {**self.default_headers, **(headers or {})}
        async with session.request(
            method.upper(),
            url,
            headers=merged_headers,
            params=params,
            json=json,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "application/json" in content_type:
                return await response.json()
            return await response.text()

    async def get_json(
        self,
        path: str = "",
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Union[str, int, float]]] = None,
    ) -> Any:
        return await self._request("GET", path, headers=headers, params=params)

    async def post_json(
        self,
        path: str = "",
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Union[str, int, float]]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self._request("POST", path, headers=headers, params=params, json=json)

    async def close(self) -> None:
        if (
            self._session
            and not self._session.closed
            and not self._session_external
            and not self._session_shared
        ):
            await self._session.close()

    async def __aenter__(self) -> "BaseAPIService":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
