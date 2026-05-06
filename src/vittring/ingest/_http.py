"""HTTP client helpers shared across adapters.

Centralizes timeouts, retries with exponential backoff, and User-Agent header.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "Vittring/0.1 (+https://vittring.karimkhalil.se)"

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


@asynccontextmanager
async def http_client(
    base_url: str | None = None,
    timeout: httpx.Timeout | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=base_url or "",
        timeout=timeout or DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        yield client


def _is_retryable_status(response: httpx.Response) -> bool:
    return response.status_code in {429, 500, 502, 503, 504}


async def get_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    max_attempts: int = 5,
) -> Any:
    """GET ``url`` with exponential backoff on 5xx and network errors."""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    ):
        with attempt:
            response = await client.get(url, params=params)
            if _is_retryable_status(response):
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
    raise RuntimeError("unreachable")  # pragma: no cover


async def post_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json_body: dict[str, Any],
    max_attempts: int = 5,
) -> Any:
    """POST ``url`` with a JSON body. Same retry semantics as GET."""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    ):
        with attempt:
            response = await client.post(
                url,
                json=json_body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            if _is_retryable_status(response):
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
    raise RuntimeError("unreachable")  # pragma: no cover
