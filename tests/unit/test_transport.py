from __future__ import annotations

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.jobs.transport import build_collection_client


def test_build_collection_client_no_proxy(test_settings: Settings) -> None:
    test_settings.job_collection_proxy_url = None
    client = build_collection_client(test_settings)
    assert isinstance(client, httpx.AsyncClient)
    assert client.headers["Accept-Language"] == "en-US,en;q=0.9"
    # transport is httpx.AsyncHTTPTransport but we don't need to introspect deeply if it succeeds


def test_build_collection_client_with_proxy(test_settings: Settings) -> None:
    test_settings.job_collection_proxy_url = SecretStr("http://proxy.example.com:8080")
    client = build_collection_client(test_settings)
    assert isinstance(client, httpx.AsyncClient)
    assert client.headers["Accept-Language"] == "en-US,en;q=0.9"
