"""Shared HTTP transport for job collection."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


def build_collection_client(
    settings: Settings,
    timeout_seconds: float = 20.0,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient configured for source scraping.

    Connects through the configured proxy if one is defined in Settings.
    """
    proxy_url = (
        settings.job_collection_proxy_url.get_secret_value()
        if settings.job_collection_proxy_url else None
    )
    
    transport_kwargs: dict[str, Any] = {
        "retries": 3,
    }
    
    transport: httpx.AsyncBaseTransport
    if proxy_url:
        transport = httpx.AsyncHTTPTransport(proxy=httpx.Proxy(proxy_url), **transport_kwargs)
    else:
        transport = httpx.AsyncHTTPTransport(**transport_kwargs)
        
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        },
        **kwargs,
    )
