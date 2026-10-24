"""Tests for configurable TLS verification."""

from __future__ import annotations

import asyncio
import ssl

from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from custom_components.loxone.pyloxone_api.loxone_http_client import (
    LoxoneAsyncHttpClient,
)


class _Response:
    """Fake ``aiohttp.ClientResponse`` — also an async context manager
    so the production ``async with self.session.get(...)`` path can
    run end-to-end in tests.
    """

    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _Session:
    closed = False

    def __init__(self) -> None:
        self.url = None
        self.kwargs = None

    def get(self, url, **kwargs):
        # Match aiohttp's ``session.get(...)`` return shape: an
        # async-context-manager that yields a response. The
        # production code does
        # ``async with self.session.get(url, **kwargs) as resp``;
        # ``_AsyncCM`` is a tiny shim that does exactly that.
        self.url = url
        self.kwargs = kwargs
        return _AsyncCM(_Response())


class _AsyncCM:
    def __init__(self, response) -> None:
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return None


async def _consume(client, endpoint):
    async with client.get(endpoint) as _resp:
        pass


def test_https_http_client_can_disable_certificate_verification() -> None:
    session = _Session()
    client = LoxoneAsyncHttpClient(
        "192.0.2.1",
        "user",
        "password",
        scheme="https",
        verify_ssl=False,
        session=session,
    )

    asyncio.run(_consume(client, "/jdev/cfg/apiKey"))

    assert session.url == "https://192.0.2.1/jdev/cfg/apiKey"
    assert session.kwargs["ssl"] is False


def test_http_client_does_not_pass_tls_options_for_plain_http() -> None:
    session = _Session()
    client = LoxoneAsyncHttpClient(
        "192.0.2.1:8080",
        "user",
        "password",
        scheme="http",
        verify_ssl=False,
        session=session,
    )

    asyncio.run(_consume(client, "/jdev/cfg/apiKey"))

    assert "ssl" not in session.kwargs


def test_websocket_uses_unverified_context_only_when_requested() -> None:
    connection = LoxoneConnection(
        host="192.0.2.1",
        port=443,
        username="user",
        password="password",
        verify_ssl=False,
    )

    ssl_context = connection._websocket_ssl_context()

    assert ssl_context is not None
    assert ssl_context.check_hostname is False
    assert ssl_context.verify_mode == ssl.CERT_NONE


def test_websocket_verifies_certificates_by_default() -> None:
    connection = LoxoneConnection(
        host="192.0.2.1",
        port=443,
        username="user",
        password="password",
    )

    assert connection._websocket_ssl_context() is None


def test_get_returns_async_context_manager() -> None:
    """``LoxoneAsyncHttpClient.get`` is an async context
    manager — the response body is read inside the ``async with``
    block and the aiohttp response is released on exit.
    """
    session = _Session()
    client = LoxoneAsyncHttpClient(
        "192.0.2.1",
        "user",
        "password",
        scheme="http",
        verify_ssl=False,
        session=session,
    )

    # Use the context manager protocol and read inside the block.
    async def read_body() -> None:
        async with client.get("/jdev/cfg/apiKey") as resp:
            assert resp.status == 200

    asyncio.run(read_body())
    # ``session.get`` was called and the request URL was the expected
    # one.
    assert session.url == "http://192.0.2.1/jdev/cfg/apiKey"
