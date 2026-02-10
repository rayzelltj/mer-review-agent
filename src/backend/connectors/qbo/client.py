from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .config import QBOConfig
from .auth import ensure_access_token_valid, refresh_access_token


class QBOHttpError(RuntimeError):
    def __init__(self, status: int, message: str, body: str | None = None):
        super().__init__(f"QBO HTTP {status}: {message}")
        self.status = status
        self.body = body


def qbo_get(
    config: QBOConfig,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout_seconds: int = 30,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    Perform an authenticated GET to the QBO API.

    Scaffolding implementation using stdlib urllib with minimal retry + refresh-on-401 support.
    """
    try:
        config = ensure_access_token_valid(config)
    except NotImplementedError:
        pass

    retries = 0
    refreshed = False
    backoff = 0.5

    while True:
        url = _build_url(config.base_url, path, params)
        req = Request(url, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("Authorization", f"Bearer {config.access_token}")

        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else None
            status = exc.code

            if status == 401 and not refreshed:
                config = refresh_access_token(config)
                refreshed = True
                continue

            if status in (429, 500, 502, 503, 504) and retries < max_retries:
                time.sleep(backoff)
                retries += 1
                backoff *= 2
                continue

            raise QBOHttpError(status, exc.reason, body) from exc
        except URLError as exc:
            if retries < max_retries:
                time.sleep(backoff)
                retries += 1
                backoff *= 2
                continue
            raise QBOHttpError(0, str(exc)) from exc


def _build_url(base_url: str, path: str, params: dict[str, Any] | None) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    url = urljoin(base_url, normalized_path)
    if params:
        url = f"{url}?{urlencode(params)}"
    return url
