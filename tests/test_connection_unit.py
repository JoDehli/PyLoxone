"""Connection-layer unit tests (no live Miniserver, no websocket).

Covers the URL helpers (``parse_loxone_url``, ``build_loxone_url``)
and the ``_apply_url`` instance method that keeps ``self.scheme`` and
``self.url`` in lockstep during Cloud-DNS redirects. Plus
``open()`` / ``start_listening()`` storage and skip behaviour.

The original suite has ~25 such tests; they are ported here one
step at a time. This file holds the tests
that do not need a homeassistant harness (no HA setup, no integration
fixture); they only need the URL table and the
``open()`` / ``start_listening()`` storage contract.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from collections import deque
from types import SimpleNamespace

import pytest

from custom_components.loxone.pyloxone_api.connection import (
    LoxoneBaseConnection,
    LoxoneConnection,
    MessageForQueue,
    SecuredCommand,
    build_loxone_url,
    parse_loxone_url,
)
from custom_components.loxone.pyloxone_api.message import (
    MessageType,
    TextMessage,
    parse_message,
)


class TestParseLoxoneUrl:
    """parse_loxone_url — input → (scheme, host[:port][/path])."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            # HTTP / HTTPS with explicit host
            ("http://192.168.1.1", ("http", "192.168.1.1")),
            ("https://192.168.1.1", ("https", "192.168.1.1")),
            # Non-default port kept
            ("http://192.168.1.1:8080", ("http", "192.168.1.1:8080")),
            ("https://192.168.1.1:8443", ("https", "192.168.1.1:8443")),
            # Default port stripped for the matching scheme
            ("http://192.168.1.1:80", ("http", "192.168.1.1")),
            ("https://192.168.1.1:443", ("https", "192.168.1.1")),
            # No scheme → defaults to http
            ("192.168.1.1", ("http", "192.168.1.1")),
            ("192.168.1.1:8080", ("http", "192.168.1.1:8080")),
            # Path preserved
            ("https://192.168.1.1/api", ("https", "192.168.1.1/api")),
            (
                "http://192.168.1.1:8080/api",
                ("http", "192.168.1.1:8080/api"),
            ),
            # Cloud DNS form (what motivated the helper)
            (
                "https://12345.loxone.cloud:443",
                ("https", "12345.loxone.cloud"),
            ),
            (
                "https://12345.loxone.cloud",
                ("https", "12345.loxone.cloud"),
            ),
        ],
    )
    def test_url_table(self, url: str, expected: tuple[str, str]) -> None:
        assert parse_loxone_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        ["", "//", "/path-only"],
    )
    def test_invalid_host_raises(self, url: str) -> None:
        with pytest.raises(ValueError):
            parse_loxone_url(url)


class TestBuildLoxoneUrl:
    """build_loxone_url — (scheme, host) → websocket URL."""

    @pytest.mark.parametrize(
        ("scheme", "host", "expected"),
        [
            ("http", "192.168.1.1", "ws://192.168.1.1/ws/rfc6455"),
            ("https", "192.168.1.1", "wss://192.168.1.1/ws/rfc6455"),
            ("ws", "192.168.1.1", "ws://192.168.1.1/ws/rfc6455"),
            ("wss", "192.168.1.1", "wss://192.168.1.1/ws/rfc6455"),
            ("http", "192.168.1.1:8080", "ws://192.168.1.1:8080/ws/rfc6455"),
            (
                "https",
                "12345.loxone.cloud",
                "wss://12345.loxone.cloud/ws/rfc6455",
            ),
        ],
    )
    def test_url_table(
        self, scheme: str, host: str, expected: str
    ) -> None:
        assert build_loxone_url(scheme, host) == expected

    def test_custom_path(self) -> None:
        assert (
            build_loxone_url("https", "192.168.1.1", path="/custom/path")
            == "wss://192.168.1.1/custom/path"
        )

    @pytest.mark.parametrize("scheme", ["ftp", "file", "", "HTTP", "HTTPS"])
    def test_unsupported_scheme_raises(self, scheme: str) -> None:
        with pytest.raises(ValueError):
            build_loxone_url(scheme, "192.168.1.1")


class TestApplyUrl:
    """_apply_url — updates scheme and url together."""

    def test_http_to_https_redirect(self) -> None:
        conn = LoxoneBaseConnection(
            host="192.168.1.1",
            username="user",
            password="password",
            port=8080,
        )
        assert conn.scheme == "http"
        assert conn.url == "192.168.1.1:8080"

        # Cloud DNS redirect: http → https, host swap, port stripped
        conn._apply_url("https", "12345.loxone.cloud")
        assert conn.scheme == "https"
        assert conn.url == "12345.loxone.cloud"

    def test_https_to_https_redirect(self) -> None:
        # User started with HTTPS; Cloud DNS still moves them around
        conn = LoxoneBaseConnection(
            host="https://192.168.1.1",
            username="user",
            password="password",
            port=443,
        )
        assert conn.scheme == "https"
        assert conn.url == "192.168.1.1"

        conn._apply_url("https", "12345.loxone.cloud")
        assert conn.scheme == "https"
        assert conn.url == "12345.loxone.cloud"

    def test_no_op_when_same(self) -> None:
        # _apply_url itself always assigns; the "skip if same" guard
        # is in the caller. Just confirm a same-value assignment
        # leaves the state intact.
        conn = LoxoneBaseConnection(
            host="192.168.1.1",
            username="user",
            password="password",
            port=8080,
        )
        original = (conn.scheme, conn.url)
        conn._apply_url(*original)
        assert (conn.scheme, conn.url) == original

    def test_build_url_after_apply_url_uses_new_scheme(self) -> None:
        # The motivating bug: applying a Cloud-DNS redirect must flip
        # the websocket URL from ws:// to wss://.
        conn = LoxoneBaseConnection(
            host="192.168.1.1",
            username="user",
            password="password",
            port=8080,
        )
        # Before redirect: ws://...
        assert build_loxone_url(conn.scheme, conn.url) == (
            "ws://192.168.1.1:8080/ws/rfc6455"
        )

        conn._apply_url("https", "12345.loxone.cloud")

        # After redirect: wss://... (this is the Cloud-DNS fix)
        assert build_loxone_url(conn.scheme, conn.url) == (
            "wss://12345.loxone.cloud/ws/rfc6455"
        )


class _FakeWebsocket:
    """Stand-in for ``websockets.ClientConnection``.

    ``async for msg in ws:`` immediately raises ``StopAsyncIteration``
    so the recv loop in ``_do_start_listening`` exits without doing
    any real protocol work. ``send`` is a no-op so the
    ``CMD_KEY_EXCHANGE`` round-trip from ``start_listening`` does not
    fail.
    """

    state = SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
    protocol = SimpleNamespace(state=SimpleNamespace(name="OPEN"))

    async def send(self, *args, **kwargs):
        return None

    async def close(self, *args, **kwargs):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _ll_response(value: str) -> bytes:
    """Wrap a JSON string in the LL response envelope used by Loxone.

    ``LLResponse`` (in ``message.py``) requires ``code``, ``control``,
    and ``value`` keys under the ``LL`` envelope.
    """
    return json.dumps(
        {"LL": {"code": 200, "control": "dev/cfg/apiKey", "value": value}}
    ).encode()


class _FakeHttpSession:
    """Fake ``aiohttp.ClientSession`` that returns canned Miniserver responses.

    Routes on URL substring:
      - ``apiKey`` → API-key response (version, snr, local).
      - ``LoxAPP3`` → empty structure file.
      - anything else → real RSA public key PEM (the public-key
        response is a plain PEM, not LL-wrapped, see
        ``connection.py:1068-1079``).

    Used by ``LoxoneAsyncHttpClient`` via ``session.get(url, **kwargs)``.
    """

    closed = False

    def __init__(self, public_pem: str) -> None:
        self.public_pem = public_pem
        # The public-key response is a CERTIFICATE (BEGIN CERTIFICATE / END
        # CERTIFICATE) per the docs at lines 1073-1079 of connection.py;
        # we generate one from the public key for the test.
        from Crypto.PublicKey import RSA

        # Same key, wrapped as a self-signed certificate body. PyCryptodome
        # exports a public key as PEM with BEGIN PUBLIC KEY headers; we
        # rewrite them to BEGIN CERTIFICATE so the production parsing
        # path is exercised.
        self.public_pem_as_cert = public_pem.replace(
            "BEGIN PUBLIC KEY", "BEGIN CERTIFICATE"
        ).replace("END PUBLIC KEY", "END CERTIFICATE")
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        # Mirror ``aiohttp.ClientSession.get()``: returns an async
        # context manager that yields the response. The production
        # ``LoxoneAsyncHttpClient.get()`` does
        # ``async with self.session.get(url, **kwargs) as resp`` and
        # reads ``resp.content`` inside the block.
        self.calls.append(url)
        if "apiKey" in url:
            body = _ll_response(
                json.dumps(
                    {
                        "version": "13.2.0",
                        "snr": "TEST-SERIAL",
                        "local": True,
                    }
                )
            )
        elif "LoxAPP3" in url:
            # LoxAPP3.json is a plain JSON document (not LL-wrapped).
            body = b"{}"
        elif "getPublicKey" in url or "pubkey" in url.lower():
            # Public-key response — the Miniserver returns a
            # certificate wrapped in an LL envelope; ``connection.py``
            # then ``replace``s the CERTIFICATE headers with PUBLIC
            # KEY headers and feeds the result to
            # ``Crypto.PublicKey.RSA.importKey``.
            body = _ll_response(self.public_pem_as_cert)
        else:
            body = b""
        return _AsyncCM(_FakeResponse(body))


class _AsyncCM:
    """Tiny async context manager shim matching aiohttp's
    ``_RequestContextManager`` shape.
    """

    def __init__(self, response) -> None:
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return None


class _FakeResponse:
    """Fake ``aiohttp.ClientResponse`` with a ``content.read()`` coroutine."""

    status = 200
    url = ""

    def __init__(self, body: bytes) -> None:
        self._body = body
        # ``connection.py`` reads the body via ``api_resp.content.read()``
        # — mirror the aiohttp attribute layout.
        self.content = self

    async def read(self) -> bytes:
        return self._body


class TestOpenStoresWebsocket:
    """``open()`` stores the websocket on ``self.connection``; a
    follow-up ``start_listening()`` does not call ``open()`` again
    when ``self.connection`` is already set.
    """

    @pytest.fixture
    def fake_http_session(self):
        """Fake aiohttp.ClientSession backed by a freshly generated RSA key."""
        from Crypto.PublicKey import RSA

        rsa_key = RSA.generate(2048)
        public_pem = rsa_key.publickey().export_key().decode()
        return _FakeHttpSession(public_pem)

    @pytest.mark.asyncio
    async def test_open_stores_websocket(
        self, monkeypatch, fake_http_session
    ):
        """After ``open()``, ``conn.connection`` is the websocket
        returned by ``wslib.connect``.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        fake_ws = _FakeWebsocket()

        async def fake_connect(*args, **kwargs):
            return fake_ws

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        assert conn.connection is None

        await conn.open(session=fake_http_session)

        # The websocket is now stored on the instance and is the same
        # object ``wslib.connect`` returned.
        assert conn.connection is fake_ws

    @pytest.mark.asyncio
    async def test_start_listening_does_not_reopen_when_connected(
        self, monkeypatch,
    ):
        """If ``self.connection`` is already set, ``start_listening()``
        must not call ``open()`` (and therefore must not call
        ``wslib.connect``) again.

        The contract was: previously ``start_listening`` did
        ``self.connection = await self.open()`` unconditionally; the
        guard ``if self.connection is None`` was added
        together with moving the assignment into ``open()`` itself.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        # If open() is called, this raises immediately. We assert
        # ``start_listening`` never triggers it.
        async def fail_open(self, *args, **kwargs):
            raise AssertionError(
                "open() must not be called when self.connection is set"
            )

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "open", fail_open
        )

        # wslib.connect must also not be called. If it is, the test
        # fails for the same reason.
        async def fail_connect(*args, **kwargs):
            raise AssertionError(
                "wslib.connect must not be called when self.connection is set"
            )

        monkeypatch.setattr(conn_mod.wslib, "connect", fail_connect)

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        # Pre-set the connection so ``open()`` reuses it.
        fake_ws = _FakeWebsocket()
        conn.connection = fake_ws
        # Pre-set a session key so ``start_listening``'s key-exchange
        # step passes its own ``if not self._session_key`` check and
        # can proceed to call ``self.connection.send(...)`` (a no-op
        # on the fake). This is the path the guard protects.
        conn._session_key = b"fake-session-key"

        # Run start_listening in a task so we can cancel it. The recv
        # loop inside _do_start_listening exits immediately on our
        # fake websocket (StopAsyncIteration), but the other
        # keep-alive / token-refresh / reconnect tasks inside
        # start_listening would otherwise run forever. We give the
        # task a brief moment to either (a) call open() and crash
        # with AssertionError, or (b) start the key-exchange send,
        # which proves the guard fired.
        #
        # When the recv ``async for`` ends naturally, the
        # loop now raises ``LoxoneConnectionClosedOk`` (close code
        # 1000 detection) so the supervisor can react immediately.
        # The fake websocket's empty ``__anext__`` triggers that
        # path, so we expect the exception when awaiting the task.
        task = asyncio.create_task(conn.start_listening())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # ``LoxoneConnectionClosedOk`` (and any other
            # recoverable exception) is the expected outcome
            # here — the test's purpose is to confirm
            # ``open()`` / ``wslib.connect`` were not called.
            pass

        # Connection was not replaced by start_listening.
        assert conn.connection is fake_ws


class TestDeferredWebsocket:
    """``open(connect_websocket=False)`` bootstraps over HTTP only;
    the next ``start_listening()`` opens the websocket right before
    the key exchange (issue #527: the Miniserver closes a websocket
    that is not authenticated within a few seconds).
    """

    @pytest.fixture
    def fake_http_session(self):
        from Crypto.PublicKey import RSA

        rsa_key = RSA.generate(2048)
        public_pem = rsa_key.publickey().export_key().decode()
        return _FakeHttpSession(public_pem)

    @staticmethod
    def _make_conn():
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    @pytest.mark.asyncio
    async def test_open_without_websocket_skips_connect(
        self, monkeypatch, fake_http_session
    ):
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        async def fail_connect(*args, **kwargs):
            raise AssertionError("wslib.connect must not be called")

        monkeypatch.setattr(conn_mod.wslib, "connect", fail_connect)

        conn = self._make_conn()
        result = await conn.open(
            session=fake_http_session, connect_websocket=False
        )

        assert result is None
        assert conn.connection is None
        assert conn.structure_file
        assert conn._session_key
        assert conn._websocket_deferred is True

    @pytest.mark.asyncio
    async def test_start_listening_connects_deferred_websocket(
        self, monkeypatch, fake_http_session
    ):
        """The deferred websocket is opened by ``start_listening``
        without repeating the HTTP bootstrap, and the key exchange is
        the first frame sent on it.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod
        from custom_components.loxone.pyloxone_api.const import (
            CMD_KEY_EXCHANGE,
        )

        sent: list[str] = []

        class _RecordingWebsocket(_FakeWebsocket):
            async def send(self, message, *args, **kwargs):
                sent.append(message)

        fake_ws = _RecordingWebsocket()
        connects = 0

        async def fake_connect(*args, **kwargs):
            nonlocal connects
            connects += 1
            return fake_ws

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        conn = self._make_conn()
        await conn.open(session=fake_http_session, connect_websocket=False)
        assert connects == 0

        async def fail_open(self, *args, **kwargs):
            raise AssertionError("open() must not run again")

        monkeypatch.setattr(conn_mod.LoxoneConnection, "open", fail_open)

        task = asyncio.create_task(conn.start_listening())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # The fake recv loop ends at once, which surfaces as a
            # recoverable closed-connection error — not under test.
            pass

        assert connects == 1
        assert sent and sent[0].startswith(CMD_KEY_EXCHANGE)
        assert conn._websocket_deferred is False

    @pytest.mark.asyncio
    async def test_close_clears_deferred_flag(
        self, monkeypatch, fake_http_session
    ):
        """After a close, a reconnect must run the full ``open()``
        bootstrap again, not just the deferred websocket connect.
        """
        conn = self._make_conn()
        await conn.open(session=fake_http_session, connect_websocket=False)

        await conn.close()

        assert conn._websocket_deferred is False


class TestExecutorParam:
    """``LoxoneBaseConnection.__init__`` accepts an optional
    ``executor`` callable, and ``open()`` uses it to off-load the
    ``json.loads(structure_file)`` parse off the event loop.

    The executor shape matches ``hass.async_add_executor_job``
    (``async def executor(target, *args)`` → awaitable returning the
    result). When ``executor is None`` (the default), the parse runs
    inline (preserving the previous behaviour for callers that don't
    pass an executor).
    """

    @pytest.fixture
    def fake_http_session(self):
        """Re-uses the canned HTTP layer from TestOpenStoresWebsocket."""
        from Crypto.PublicKey import RSA

        rsa_key = RSA.generate(2048)
        public_pem = rsa_key.publickey().export_key().decode()
        return _FakeHttpSession(public_pem)

    @pytest.mark.asyncio
    async def test_open_uses_executor_for_structure_file_parse(
        self, monkeypatch, fake_http_session
    ):
        """When an executor is supplied, ``json.loads(structure_file)``
        is invoked via the executor (off the event loop), not directly
        on the data bytes.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        async def fake_connect(*args, **kwargs):
            return _FakeWebsocket()

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        # The executor records every (target, args) pair it's asked to
        # run. We assert ``json.loads`` is invoked via it.
        calls: list[tuple] = []

        async def fake_executor(target, *args):
            calls.append((target, args))
            return target(*args)

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
            executor=fake_executor,
        )

        await conn.open(session=fake_http_session)

        # At least one call must have been ``json.loads`` on the
        # structure-file payload.
        json_loads_calls = [
            (t, a) for (t, a) in calls if t is json.loads
        ]
        assert len(json_loads_calls) == 1
        # The first positional arg of json.loads was the LoxAPP3 body.
        target, args = json_loads_calls[0]
        assert isinstance(args[0], (bytes, bytearray))
        # Decoding the parsed payload back to JSON should round-trip
        # to the empty-dict structure file the fake HTTP layer returned.
        assert json.loads(args[0]) == {}

    @pytest.mark.asyncio
    async def test_open_runs_json_loads_inline_when_no_executor(
        self, monkeypatch, fake_http_session
    ):
        """When ``executor`` is ``None`` (the default), ``open()``
        still parses the structure file successfully — inline.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        async def fake_connect(*args, **kwargs):
            return _FakeWebsocket()

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
            # No executor — parse runs inline.
        )
        assert conn.executor is None

        await conn.open(session=fake_http_session)

        # The structure file was populated (it was the empty
        # ``{}`` the fake HTTP layer returns).
        assert conn.structure_file is not None
        # ``softwareVersion`` is back-filled with ``miniserver_version``
        # which the API-key response set to ``[13, 2, 0]``.
        assert conn.structure_file.get("softwareVersion") == [13, 2, 0]

    @pytest.mark.asyncio
    async def test_executor_exceptions_propagate(
        self, monkeypatch, fake_http_session
    ):
        """An exception raised by the executor (or its target)
        propagates out of ``open()`` rather than being swallowed.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        async def fake_connect(*args, **kwargs):
            return _FakeWebsocket()

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        async def failing_executor(target, *args):
            raise RuntimeError("executor boom")

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
            executor=failing_executor,
        )

        with pytest.raises(RuntimeError, match="executor boom"):
            await conn.open(session=fake_http_session)

    def test_default_executor_is_none(self):
        """The default value of ``executor`` is ``None`` — preserves
        the previous behaviour for tests and standalone scripts
        that don't pass an executor.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        assert conn.executor is None


class TestSecuredQueueDrain:
    """``_secured_queue`` is a ``deque[SecuredCommand]`` that
    the ``getvisusalt`` handler drains via ``_drain_secured_queue``.
    The pure-function tests below cover the drain helper directly,
    without a live Miniserver.
    """

    def _make_conn(self) -> LoxoneConnection:
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    def _set_visual_hash(self, conn, key="aa" * 32, salt="bb" * 16, hash_alg="SHA1"):
        from custom_components.loxone.pyloxone_api.loxone_token import (
            LxJsonKeySalt,
        )

        kh = LxJsonKeySalt()
        kh.key = key
        kh.salt = salt
        kh.hash_alg = hash_alg
        conn._visual_hash = kh

    @pytest.mark.asyncio
    async def test_send_next_with_empty_queue(self):
        conn = self._make_conn()
        self._set_visual_hash(conn)
        assert conn._secured_queue == deque()
        assert await conn._send_next_secured_command() is False
        assert conn._message_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_send_next_single_command(self):
        conn = self._make_conn()
        self._set_visual_hash(conn)

        conn._secured_queue.append(
            SecuredCommand("dev-uuid-1", "value", "44")
        )
        assert await conn._send_next_secured_command() is True
        assert conn._secured_queue == deque()

        # The command is on the message queue as a
        # MessageForQueue with flag=True.
        assert conn._message_queue.qsize() == 1
        item = conn._message_queue.get_nowait()
        assert isinstance(item, MessageForQueue)
        assert item.flag is True
        # The command text starts with ``jdev/sps/ios/{hmac}/``.
        assert item.command.startswith("jdev/sps/ios/")
        assert item.command.endswith("/dev-uuid-1/value")

    @pytest.mark.asyncio
    async def test_one_command_per_reply_in_fifo_order(self):
        """Each call (= one getvisusalt reply) releases exactly one
        command, oldest first.
        """
        conn = self._make_conn()
        self._set_visual_hash(conn)

        for i in range(3):
            conn._secured_queue.append(
                SecuredCommand(f"dev-{i}", f"v{i}", f"c{i}")
            )

        for i in range(3):
            assert await conn._send_next_secured_command() is True
            assert len(conn._secured_queue) == 2 - i
            item = conn._message_queue.get_nowait()
            assert item.command.endswith(f"/dev-{i}/v{i}")

    @pytest.mark.asyncio
    async def test_send_next_without_visual_hash_consumes_command(self):
        """Without a visual hash the command is consumed but nothing
        is sent (logged at DEBUG by ``_secured_command_text``).
        """
        conn = self._make_conn()
        assert conn._visual_hash is None
        conn._secured_queue.append(SecuredCommand("dev-0", "v", "c"))

        assert await conn._send_next_secured_command() is False
        assert conn._secured_queue == deque()
        assert conn._message_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_send_next_unknown_hash_alg_sends_nothing(
        self, caplog: pytest.LogCaptureFixture
    ):
        """An unrecognised hash algorithm drops that command (logged
        at ERROR) and nothing reaches the message queue.
        """
        import logging

        conn = self._make_conn()
        # ``hash_alg="UNKNOWN"`` is not in {"SHA1", "SHA256"} — the
        # helper will log and return ``None``.
        self._set_visual_hash(conn, hash_alg="UNKNOWN-ALG")

        conn._secured_queue.append(
            SecuredCommand("dev-x", "v", "c")
        )

        with caplog.at_level(
            logging.ERROR,
            logger="custom_components.loxone.pyloxone_api.connection",
        ):
            assert await conn._send_next_secured_command() is False

        assert conn._message_queue.qsize() == 0
        assert any(
            "Unrecognised hash algorithm" in r.message
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_expired_command_is_dropped_not_sent(
        self, caplog: pytest.LogCaptureFixture
    ):
        """A command whose reply never came is not sent with a later
        reply; the next fresh command is.
        """
        import logging
        import time

        from custom_components.loxone.pyloxone_api.const import (
            SECURED_COMMAND_TIMEOUT,
        )

        conn = self._make_conn()
        self._set_visual_hash(conn)
        conn._secured_queue.append(
            SecuredCommand(
                "open-gate",
                "pulse",
                "1234",
                created=time.monotonic() - SECURED_COMMAND_TIMEOUT - 1,
            )
        )
        conn._secured_queue.append(SecuredCommand("disarm", "off", "1234"))

        with caplog.at_level(logging.WARNING):
            assert await conn._send_next_secured_command() is True

        item = conn._message_queue.get_nowait()
        assert item.command.endswith("/disarm/off")
        assert conn._message_queue.qsize() == 0
        assert "open-gate" in caplog.text

    def test_secured_queue_is_deque_not_queue(self):
        """Regression net: ``_secured_queue`` must be a ``deque`` of
        ``SecuredCommand``, not an ``asyncio.Queue`` of coroutines.
        """
        conn = self._make_conn()
        assert isinstance(conn._secured_queue, deque)
        # Empty by default; no coroutine-throwing initial state.
        assert len(conn._secured_queue) == 0

    @pytest.mark.asyncio
    async def test_send_secured_websocket_command_enqueues_secured_command(self):
        """``send_secured_websocket_command`` puts a
        ``SecuredCommand`` on the deque with the exact (device_uuid,
        value, code) tuple — and only one entry per call (no
        coroutine objects queued).
        """
        conn = self._make_conn()
        # Pre-attach a fake ws whose ``send`` is a no-op, so the
        # key-exchange round-trip in ``start_listening`` doesn't
        # blow up here — this test only exercises the secured
        # enqueue path.
        conn.connection = _FakeWebsocket()

        await conn.send_secured_websocket_command("dev-uuid", 1, "1234")

        assert len(conn._secured_queue) == 1
        entry = conn._secured_queue[0]
        assert isinstance(entry, SecuredCommand)
        assert entry.device_uuid == "dev-uuid"
        assert entry.value == 1
        assert entry.code == "1234"

    @pytest.mark.asyncio
    async def test_close_clears_secured_queue(self):
        conn = self._make_conn()
        conn.connection = _FakeWebsocket()

        for i in range(3):
            conn._secured_queue.append(
                SecuredCommand(f"dev-{i}", f"v{i}", f"c{i}")
            )
        assert len(conn._secured_queue) == 3

        await conn.close()

        assert len(conn._secured_queue) == 0


class TestGetvisusaltDoesNotClobberSessionKey:
    """The ``getvisusalt`` handler must not touch
    ``self._key``.

    The previous implementation did
    ``self._key = value_dict.get("value", "")`` on every
    ``getvisusalt`` event — the ``value`` field there is the
    *visual-hash* AES key, not the session AES key from
    ``getkey2``. After the first secured command cycle,
    ``_hash_credentials`` would compute the wrong HMAC and
    auth fails.

    ``self._visual_hash.key`` (set by
    ``LxJsonKeySalt.read_user_salt_response``) is the right
    place for the visual-hash key — it's what
    ``_secured_command_text`` reads. ``self._key`` is the session
    AES key, set by the ``getkey`` / ``getkey2`` handlers.
    """

    def _getvisusalt_message(self) -> str:
        """A minimal ``getvisusalt`` TextMessage payload.

        ``LL.value`` is a dict with ``key``/``salt``/``hashAlg``
        fields — ``LxJsonKeySalt.read_user_salt_response`` parses
        the whole message and indexes ``js["LL"]["value"]["key"]``
        directly (no inner JSON-decode step). The control contains
        ``getvisusalt`` so the handler matches the substring.
        """
        return json.dumps(
            {
                "LL": {
                    "control": "jdev/sps/getvisusalt/user",
                    "code": "200",
                    "value": {
                        "key": "aa" * 32,
                        "salt": "bb" * 16,
                        "hashAlg": "SHA1",
                    },
                }
            }
        )

    @pytest.mark.asyncio
    async def test_getvisusalt_does_not_clobber_session_key(self):
        """Feed a ``getvisusalt`` event to ``_websocket_event`` and
        assert ``self._key`` is left exactly as it was before.
        """
        from custom_components.loxone.pyloxone_api.message import (
            TextMessage,
            parse_message,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        # Pre-set ``_key`` to a recognisable session-key value (32
        # bytes hex, like a real AES-256 session key). The bug
        # would replace this with the visual-hash key from the
        # getvisusalt message.
        session_key = "11" * 32
        conn._key = session_key

        # Visual hash starts as None; we expect the handler to
        # populate ``_visual_hash.key`` but leave ``_key`` alone.
        assert conn._visual_hash is None

        msg_str = self._getvisusalt_message()
        msg = parse_message(msg_str, MessageType.TEXT)

        # Drive the relevant branch of ``_websocket_event``
        # directly — feeding a parsed TextMessage bypasses the
        # header-tracking logic in ``_do_start_listening``.
        await conn._websocket_event(msg)

        # Session key unchanged.
        assert conn._key == session_key
        # Visual hash was populated from the response.
        assert conn._visual_hash is not None
        assert conn._visual_hash.key == "aa" * 32
        assert conn._visual_hash.salt == "bb" * 16
        assert conn._visual_hash.hash_alg == "SHA1"

    @pytest.mark.asyncio
    async def test_repeated_getvisusalt_keeps_session_key_stable(self):
        """Three back-to-back ``getvisusalt`` events must all
        leave ``self._key`` unchanged — the previous bug would
        re-clobber it on each one.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        session_key = "22" * 32
        conn._key = session_key

        for _ in range(3):
            msg_str = self._getvisusalt_message()
            msg = parse_message(msg_str, MessageType.TEXT)
            await conn._websocket_event(msg)
            assert conn._key == session_key

    @pytest.mark.asyncio
    async def test_getvisusalt_still_populates_visual_hash(self):
        """The fix must not break the secure-command path:
        ``self._visual_hash`` must still be populated so
        ``_secured_command_text`` can build wire commands.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        msg_str = self._getvisusalt_message()
        msg = parse_message(msg_str, MessageType.TEXT)
        await conn._websocket_event(msg)

        # ``_secured_command_text`` reads ``self._visual_hash.key``
        # — assert it is set to the value from the response.
        text = conn._secured_command_text("dev-1", 1, "1234")
        assert text is not None
        assert text.startswith("jdev/sps/ios/")
        assert text.endswith("/dev-1/1")

class TestGetWithRetry:
    """``_get_with_retry`` — bounded exponential backoff for bootstrap GETs.

    The helper wraps :meth:`LoxoneConnection.open`'s three GETs
    (``CMD_GET_API_KEY``, ``LOXAPPPATH``, ``CMD_GET_PUBLIC_KEY``) with
    an exponential-backoff retry loop. The tests below drive the
    helper directly with controllable fake connectors so we can
    assert the retry / backoff / give-up behaviour without
    instantiating the full open() pipeline.
    """

    @staticmethod
    def _make_failing_connector(fail_count: int, body: bytes = b"OK"):
        """Build a ``LoxoneAsyncHttpClient``-shaped fake.

        The first ``fail_count`` GETs raise ``ConnectionError``; the
        next one (and any subsequent) returns ``(body, final_url)``.
        Each GET records the URL it was asked for so tests can
        assert the helper retried.
        """
        calls: list[str] = []

        class _FakeConnector:
            def get(self_inner, url, **kwargs):
                calls.append(url)
                if len(calls) <= fail_count:
                    raise ConnectionError(
                        f"simulated transient failure {len(calls)}/{fail_count}"
                    )

                class _Resp:
                    def __init__(self):
                        self.url = url
                        # ``content.read`` must be a coroutine
                        # *function* (callable returning awaitable),
                        # not a coroutine object — the production
                        # code does ``await resp.content.read()``.
                        self.content = _Content(body)

                return _AsyncCM(_Resp())

        return _FakeConnector(), calls

    @pytest.mark.asyncio
    async def test_succeeds_first_try_no_retry(self):
        """When the GET succeeds on the first attempt, no retry
        happens and the body / URL come back unchanged.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        connector, calls = self._make_failing_connector(fail_count=0)
        body, url = await conn._get_with_retry(
            "/jdev/cfg/apiKey", connector
        )
        assert body == b"OK"
        assert url == "/jdev/cfg/apiKey"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        """Two transient failures followed by success → the helper
        calls the connector three times in total and returns the
        successful body.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        connector, calls = self._make_failing_connector(fail_count=2)
        body, url = await conn._get_with_retry(
            "/jdev/cfg/apiKey", connector
        )
        assert body == b"OK"
        assert url == "/jdev/cfg/apiKey"
        assert len(calls) == 3  # 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_gives_up_after_max_tries(self):
        """When every attempt fails, the helper raises the last
        exception after exactly ``max_tries`` attempts.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        connector, calls = self._make_failing_connector(fail_count=100)
        with pytest.raises(ConnectionError):
            await conn._get_with_retry(
                "/jdev/cfg/apiKey",
                connector,
                max_tries=3,
                base_delay=0.0,  # don't actually wait between attempts
            )
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_doubles_each_attempt(self):
        """The sleep between attempt N and N+1 is approximately
        ``base * 2**N`` (within the ±20% jitter).  We assert the
        call timestamps are at least that far apart.
        """
        import time as _time

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        connector, calls = self._make_failing_connector(fail_count=3)
        timestamps: list[float] = []

        original_sleep = asyncio.sleep

        async def _record_sleep(delay):
            timestamps.append((_time.monotonic(), delay))
            # Don't actually sleep — keep the test fast.
            return await original_sleep(0)

        # Patch ``asyncio.sleep`` *inside the connection module* so
        # the helper's ``await asyncio.sleep(...)`` is intercepted.
        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        original_module_sleep = conn_mod.asyncio.sleep
        conn_mod.asyncio.sleep = _record_sleep
        try:
            await conn._get_with_retry(
                "/jdev/cfg/apiKey",
                connector,
                max_tries=4,
                base_delay=0.1,
                max_delay=10.0,
            )
        finally:
            conn_mod.asyncio.sleep = original_module_sleep

        # Three failures → three sleeps (after attempt 1, 2, 3).
        assert len(timestamps) == 3
        # Sleep delays (no jitter, since we passed base_delay small
        # enough that max_delay won't kick in):
        # attempt 1 → attempt 2: 0.1 * 2**0 = 0.1 (±20%)
        # attempt 2 → attempt 3: 0.1 * 2**1 = 0.2 (±20%)
        # attempt 3 → attempt 4: 0.1 * 2**2 = 0.4 (±20%)
        for delay, expected in zip(
            [t[1] for t in timestamps], [0.1, 0.2, 0.4]
        ):
            assert expected * 0.8 <= delay <= expected * 1.2, (
                f"delay {delay} outside ±20% of expected {expected}"
            )

    @pytest.mark.asyncio
    async def test_catches_loxone_service_unavailable(self):
        """``LoxoneServiceUnAvailableError`` is a retried class.

        This mirrors the 503 / "Miniserver restarting" case.
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneServiceUnAvailableError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        calls: list[str] = []

        class _Conn:
            def get(self_inner, url, **kwargs):
                calls.append(url)
                if len(calls) <= 1:
                    raise LoxoneServiceUnAvailableError("miniserver busy")

                class _Resp:
                    def __init__(self):
                        self.url = url
                        self.content = _Content(b"OK")

                return _AsyncCM(_Resp())

        body, _ = await conn._get_with_retry(
            "/jdev/cfg/apiKey", _Conn(), max_tries=3, base_delay=0.0
        )
        assert body == b"OK"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_catches_aiohttp_client_error(self):
        """``aiohttp.ClientError`` (catch-all aiohttp transient
        error) is retried.
        """
        import aiohttp

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        calls: list[str] = []

        class _Conn:
            def get(self_inner, url, **kwargs):
                calls.append(url)
                if len(calls) <= 1:
                    raise aiohttp.ClientError("transient")

                class _Resp:
                    def __init__(self):
                        self.url = url
                        self.content = _Content(b"OK")

                return _AsyncCM(_Resp())

        body, _ = await conn._get_with_retry(
            "/jdev/cfg/apiKey", _Conn(), max_tries=3, base_delay=0.0
        )
        assert body == b"OK"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_max_delay_caps_exponential_growth(self):
        """The sleep delay is capped at ``max_delay`` — without
        the cap, a long-lived outage would back off to hours.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        # ``fail_count`` is large enough that every retryable attempt
        # in this test fails — we want to assert the cap, not a
        # success-after-N-failures path.
        connector, _ = self._make_failing_connector(fail_count=100)
        delays: list[float] = []

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        original_sleep = conn_mod.asyncio.sleep

        async def _record_sleep(delay):
            delays.append(delay)
            return await original_sleep(0)

        original_module_sleep = conn_mod.asyncio.sleep
        conn_mod.asyncio.sleep = _record_sleep
        try:
            with pytest.raises(ConnectionError):
                await conn._get_with_retry(
                    "/jdev/cfg/apiKey",
                    connector,
                    max_tries=6,
                    base_delay=10.0,
                    max_delay=15.0,
                )
        finally:
            conn_mod.asyncio.sleep = original_module_sleep

        # Without the cap, attempt 5 would be 10 * 2**4 = 160.
        # With max_delay=15, all attempts after attempt 1 stay
        # within 15 ± 20% (jitter).
        for d in delays:
            assert d <= 15.0 * 1.2, f"delay {d} exceeds max_delay+jitter"


async def _async_read_removed(body: bytes):
    """Removed — use :class:`_Content` instead.

    Kept as a stub so an old import (if any) raises clearly. The
    ``_Content`` class below provides a coroutine-function ``read``
    matching the production aiohttp shape.
    """
    raise RuntimeError(
        "_async_read was replaced by _Content — see TestGetWithRetry"
    )


class _Content:
    """Minimal aiohttp ``StreamReader`` shim with a single-byte body.

    The production code does ``await resp.content.read()``; the
    real ``aiohttp.StreamReader.read`` is a coroutine function. We
    return a coroutine function that yields the canned ``body``.
    """

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self) -> bytes:
        return self._body


class TestBuildWebsocketOptions:
    """``_build_websocket_options`` — kwargs for ``wslib.connect``.

    The Miniserver's own 30 s keepalive is the single liveness
    channel (the websockets-library Ping/Pong is redundant and
    races the keepalive timer). Verify the helper passes
    ``ping_interval=None`` and an explicit ``close_timeout``.
    """

    def test_ping_interval_is_disabled(self):
        """``ping_interval=None`` — the library's Ping/Pong must
        be off so the Loxone keepalive is the single liveness
        signal.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        opts = conn._build_websocket_options()
        assert opts["ping_interval"] is None

    def test_close_timeout_is_explicit(self):
        """``close_timeout`` must be set to
        :data:`WEBSOCKET_CLOSE_TIMEOUT` so a slow Miniserver close
        ack doesn't hang the integration.
        """
        from custom_components.loxone.pyloxone_api.const import (
            WEBSOCKET_CLOSE_TIMEOUT,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        opts = conn._build_websocket_options()
        assert opts["close_timeout"] == WEBSOCKET_CLOSE_TIMEOUT
        # Sanity — the constant is sane.
        assert 0 < WEBSOCKET_CLOSE_TIMEOUT <= 60

    def test_options_contain_required_keys(self):
        """The keys consumed by the open() path: open_timeout,
        create_connection, compression, max_size, plus the two
        new ones.
        """
        from custom_components.loxone.pyloxone_api.const import (
            MAX_WEBSOCKET_MESSAGE_SIZE,
        )
        from custom_components.loxone.pyloxone_api.websocket_protocol import (
            LoxoneClientConnection,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        opts = conn._build_websocket_options()
        assert opts["create_connection"] is LoxoneClientConnection
        assert opts["compression"] is None
        assert opts["max_size"] == MAX_WEBSOCKET_MESSAGE_SIZE
        # ``open_timeout`` defaults to ``self.timeout or TIMEOUT``.
        assert opts["open_timeout"] == conn.timeout or 30

    def test_open_timeout_honours_instance_timeout(self):
        """If the caller passed an explicit ``timeout=``, that
        value is used for ``open_timeout`` (not the const default).
        """
        from custom_components.loxone.pyloxone_api.const import TIMEOUT

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
            timeout=5.0,
        )
        opts = conn._build_websocket_options()
        assert opts["open_timeout"] == 5.0
        # Sanity that the const value differs so the test actually
        # exercises the override path.
        assert TIMEOUT != 5.0


class TestSpawnTask:
    """``_spawn_task`` / ``_prune_tasks`` — tracked background tasks.

    A bare ``asyncio.create_task(...)`` swallows the task's
    exception if the coroutine raises and no one awaits the
    resulting task. ``_spawn_task`` keeps a set of in-flight tasks;
    ``_prune_tasks`` reports unhandled exceptions at WARNING and
    lets ``close()`` cancel whatever is left. Pruning is done in
    bulk rather than through a per-task done callback, because a
    done callback costs one extra event-loop callback per spawned
    task — measurable on the recv hot path.
    """

    @pytest.mark.asyncio
    async def test_spawn_task_returns_task(self):
        """``_spawn_task(coro, name)`` returns the created
        ``asyncio.Task``, tracks it, and pruning removes it only
        once it has finished.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        assert conn._tasks == set()

        async def _noop():
            return 42

        task = conn._spawn_task(_noop(), name="test.noop")
        try:
            assert isinstance(task, asyncio.Task)
            assert task in conn._tasks
            assert task.get_name() == "test.noop"
            result = await task
            assert result == 42
            # Removal happens in bulk, not in a done callback.
            assert task in conn._tasks
            conn._prune_tasks()
            assert task not in conn._tasks
        finally:
            # Defensive: clear anything that might still be tracked.
            conn._tasks.clear()

    @pytest.mark.asyncio
    async def test_prune_spawns_automatically_past_threshold(self):
        """Spawning past ``_TASK_PRUNE_THRESHOLD`` prunes the
        finished tasks without an explicit call.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def _ok():
            return None

        try:
            for _ in range(conn_mod._TASK_PRUNE_THRESHOLD + 8):
                conn._spawn_task(_ok(), name="test.ok")
                await asyncio.sleep(0)
            # Every task has finished and the set has been pruned
            # down to at most the threshold.
            assert len(conn._tasks) <= conn_mod._TASK_PRUNE_THRESHOLD
            assert all(t.done() for t in conn._tasks)
        finally:
            conn._tasks.clear()

    @pytest.mark.asyncio
    async def test_prune_logs_unhandled_exception(self):
        """A background task that raises must log at WARNING —
        not silently swallow the exception.

        The report happens when the tracked set is pruned (bulk,
        not per task), so the test asserts both halves: nothing is
        logged while the set is untouched, and pruning removes the
        task and emits the WARNING.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def _boom():
            raise RuntimeError("simulated background failure")

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            task = conn._spawn_task(_boom(), name="test.boom")
            assert task in conn._tasks
            # Wait for the task to finish.
            await asyncio.sleep(0)
            assert task.done()
            exc = task.exception()
            assert isinstance(exc, RuntimeError)
            assert "simulated background failure" in str(exc)
            # Not reported yet — pruning is what surfaces it.
            assert not warn.called
            conn._prune_tasks()

        assert task not in conn._tasks
        assert warn.called, (
            "expected _LOGGER.warning to be called for a "
            "background task that raised"
        )
        # The format string is "Background task %r raised: %s";
        # the second positional arg is the task name.
        first_call_args = warn.call_args_list[0]
        # The first positional arg is the format string.
        assert "Background task" in str(first_call_args[0][0])
        # The second positional arg is the task name (from %r).
        positional_args = first_call_args[0]
        assert "test.boom" in positional_args, (
            f"task name not in call args: {positional_args!r}"
        )

    @pytest.mark.asyncio
    async def test_prune_silent_on_normal_completion(self):
        """A task that completes normally produces no WARNING
        (the common case), even when pruned.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def _ok():
            return None

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            task = conn._spawn_task(_ok(), name="test.ok")
            for _ in range(5):
                await asyncio.sleep(0)
                if task.done():
                    break
            assert task.done()
            conn._prune_tasks()

        assert task not in conn._tasks
        assert not warn.called

    @pytest.mark.asyncio
    async def test_cancelled_task_does_not_log(self):
        """A task that was cancelled is a normal lifecycle event
        and must not log at WARNING.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def _long():
            await asyncio.sleep(60)

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            task = conn._spawn_task(_long(), name="test.long")
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            for _ in range(5):
                await asyncio.sleep(0)
            conn._prune_tasks()

        assert not warn.called


class TestAuthenticatedEvent:
    """``_authenticated_event`` — synchronises the refresh loop
    with the first successful token response.

    Before: the refresh loop slept 20 s then clamped its
    countdown to 1 s if the token wasn't ready yet. After: it
    blocks on ``_authenticated_event.wait()`` and starts its
    countdown the moment the first token arrives. A consecutive
    failure counter escalates to ``LoxoneTokenError`` after
    ``TOKEN_REFRESH_MAX_FAILURES`` cycles.
    """

    def test_event_starts_unset(self):
        """``_authenticated_event`` must start unset — the
        refresh loop should block until the first token.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        assert not conn._authenticated_event.is_set()

    @pytest.mark.asyncio
    async def test_cached_token_authentication_sets_event(self):
        """A successful ``authwithtoken`` response must also
        release the token-refresh gate. Cached-token startup does
        not receive a new ``gettoken``/``getjwt`` response.
        """
        from custom_components.loxone.pyloxone_api.connection import (
            LoxoneConnection,
        )
        from custom_components.loxone.pyloxone_api.message import TextMessage

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        response = TextMessage(
            '{"LL":{"control":"jdev/sys/authwithtoken",'
            '"value":"OK","code":"200"}}'
        )

        await conn._websocket_event(response)

        assert conn._authenticated_event.is_set()

    @pytest.mark.asyncio
    async def test_event_can_be_set_and_awaited(self):
        """The event is a normal ``asyncio.Event`` and can be
        awaited / set.
        """
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def _set_after():
            await asyncio.sleep(0.05)
            conn._authenticated_event.set()

        # Start the setter; await the event. The wait should
        # return when the setter fires.
        asyncio.create_task(_set_after())
        await asyncio.wait_for(conn._authenticated_event.wait(), timeout=1.0)
        assert conn._authenticated_event.is_set()

    @pytest.mark.asyncio
    async def test_maybe_escalate_raises_after_max_failures(self):
        """``_maybe_escalate_auth(N)`` raises
        ``LoxoneAuthEscalatedError`` once N reaches
        ``TOKEN_REFRESH_MAX_FAILURES`` and is a no-op below that.
        """
        from custom_components.loxone.pyloxone_api.const import (
            TOKEN_REFRESH_MAX_FAILURES,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneAuthEscalatedError,
            LoxoneTokenError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        # Below the threshold — no exception.
        for n in range(1, TOKEN_REFRESH_MAX_FAILURES):
            await conn._maybe_escalate_auth(n)

        # At the threshold — raises. It must NOT be a
        # ``LoxoneTokenError``: the supervisor retries those (that is
        # the token-expiry self-heal), while this one has to be
        # escalated.
        with pytest.raises(LoxoneAuthEscalatedError):
            await conn._maybe_escalate_auth(TOKEN_REFRESH_MAX_FAILURES)
        assert not issubclass(
            LoxoneAuthEscalatedError, LoxoneTokenError
        )
        # And beyond.
        with pytest.raises(LoxoneAuthEscalatedError):
            await conn._maybe_escalate_auth(TOKEN_REFRESH_MAX_FAILURES + 5)


class TestCheckAuthResponse:
    """``_check_auth_response`` — central policy for auth-handler LL codes.

    Before: each of the five auth handlers logged the error and
    returned. Wrong-password restarts would silently keep
    retrying. After: a single helper inspects the code, raises
    :class:`LoxoneUnauthorisedError` for 401/4003, logs at
    WARNING for other non-200 codes, and is a no-op for 200.
    """

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    def _msg(self, code: int) -> SimpleNamespace:
        return SimpleNamespace(code=code)

    def test_code_200_is_noop(self, conn):
        """200 (or equivalent) → no exception, no log."""
        # Just call; absence of exception is the assertion.
        conn._check_auth_response(self._msg(200), "gettoken")

    def test_missing_code_is_noop(self, conn):
        """Some test messages may not have a ``code`` attribute —
        the helper should treat that as 'no opinion' rather
        than crashing.
        """
        conn._check_auth_response(SimpleNamespace(), "gettoken")

    def test_401_raises_unauthorised(self, conn):
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        with pytest.raises(LoxoneUnauthorisedError):
            conn._check_auth_response(self._msg(401), "gettoken")

    def test_4003_raises_unauthorised(self, conn):
        """Legacy Miniserver firmware returns 4003 for
        unauthorised (instead of the modern 401).
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        with pytest.raises(LoxoneUnauthorisedError):
            conn._check_auth_response(self._msg(4003), "getkey2")

    def test_other_non_ok_logs_at_warning(self, conn):
        """Codes outside the unauthorised set (e.g. 500) are
        logged at WARNING but do NOT raise — the auth handler
        decides what to do.
        """
        # Just call; absence of exception is the assertion. The
        # log line is verified in the next test.
        conn._check_auth_response(self._msg(500), "getkey")

    def test_other_non_ok_logs_warning(self, conn):
        """The warning is emitted via the production logger.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            conn._check_auth_response(self._msg(500), "getkey")
        assert warn.called
        # The context ("getkey") and the code (500) are in the
        # log message.
        positional = warn.call_args_list[0][0]
        assert "getkey" in str(positional)
        assert "500" in str(positional)


class TestTokenChangeCallback:
    """``_signal_token_changed`` / ``kill_token``.

    The integration passes a ``token_change_callback`` so a
    fresh token (initial auth or refresh) can be persisted to
    HA's ``ConfigEntry.data``. ``kill_token`` invalidates the
    JWT on the Miniserver side so a subsequent restart can't
    reuse a token the previous session already abandoned.
    """

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    def test_signal_no_callback_is_noop(self, conn):
        """If no callback was passed, ``_signal_token_changed``
        is a no-op (the common case for tests / non-HA
        callers).
        """
        # Just call; absence of exception is the assertion.
        conn._signal_token_changed()

    def test_signal_invokes_sync_callback(self, conn):
        """A plain function callback is invoked with the token
        dict and the result is dropped (sync callbacks don't
        need awaiting).
        """
        seen: list[dict] = []

        def cb(token_dict):
            seen.append(token_dict)

        # Manually inject the callback (the param is on
        # ``LoxoneBaseConnection.__init__`` but the field
        # name is ``_token_change_callback``).
        conn._token_change_callback = cb
        conn._token.token = "abc123"
        conn._token.valid_until = 9999999999
        conn._token.key = ""
        conn._token.hash_alg = "SHA1"

        conn._signal_token_changed()
        assert len(seen) == 1
        assert seen[0]["token"] == "abc123"
        assert seen[0]["valid_until"] == 9999999999
        assert seen[0]["hash_alg"] == "SHA1"

    def test_signal_async_callback_spawns_task(self, conn):
        """An async callback is detected via ``iscoroutine``;
        the coroutine is handed to ``_spawn_task`` so the
        caller isn't blocked and any exception is logged via
        the standard done-callback path.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        async def acb(token_dict):
            return None

        with patch.object(conn_mod.LoxoneConnection, "_spawn_task") as spawn:
            conn._token_change_callback = acb
            conn._token.token = "tok"
            conn._token.valid_until = 100
            conn._token.key = ""
            conn._token.hash_alg = "SHA1"

            conn._signal_token_changed()
        assert spawn.called
        # The first arg of the call is a coroutine, the second
        # is the name we use for the spawned task.
        call = spawn.call_args
        assert call[0][0].__class__.__name__ == "coroutine"
        assert call[1]["name"] == "loxone.token-changed"

    def test_signal_swallows_callback_exception(self, conn):
        """A callback that raises must not break the token
        handler — the exception is logged at WARNING, not
        re-raised.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        def bad_cb(token_dict):
            raise RuntimeError("simulated persistence failure")

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            conn._token_change_callback = bad_cb
            conn._token.token = "tok"
            conn._token.valid_until = 100
            conn._token.key = ""
            conn._token.hash_alg = "SHA1"

            # No exception propagates out of the call.
            conn._signal_token_changed()
        assert warn.called

    @pytest.mark.asyncio
    async def test_kill_token_without_token_is_noop(self, conn):
        """If ``self._token.token`` is empty, ``kill_token``
        is a no-op — there's nothing to invalidate.
        """
        # ``conn._token`` is a fresh LoxoneToken (token="").
        await conn.kill_token()  # must not raise

    @pytest.mark.asyncio
    async def test_kill_token_sends_command(self, conn, monkeypatch):
        """With a token set, ``kill_token`` sends
        ``jdev/sys/killtoken/<token>/<user>`` via
        ``_send_text_command``.

        Both path segments matter: the Miniserver answers 400 and
        keeps the token alive when the user segment is missing.
        The user is the percent-encoded form used everywhere else
        in the protocol layer, so a non-ASCII username must not
        break the command path.
        """
        sent: list[str] = []

        async def fake_send(self, command, encrypted=True):
            sent.append((command, encrypted))

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        # Patch the method on the *class* so it works on the
        # instance too.
        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "_send_text_command", fake_send
        )
        # Percent-encoded, to prove ``kill_token`` sends the
        # encoded username and not the raw one.
        monkeypatch.setattr(conn, "_encoded_username", "b%C3%B6b")

        conn._token.token = "test-jwt-abc"
        await conn.kill_token()
        assert len(sent) == 1
        assert sent[0][0] == "jdev/sys/killtoken/test-jwt-abc/b%C3%B6b"
        # The raw token must not cross the network in clear text
        # (ws:// on Gen1): the kill goes through command encryption.
        assert sent[0][1] is True

    @pytest.mark.asyncio
    async def test_kill_token_never_logs_the_token(self, conn, monkeypatch, caplog):
        """Neither ``kill_token`` nor ``_send_text_command`` may put
        the raw token into the (DEBUG) log.
        """
        import logging

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        # Run the real ``_send_text_command`` up to the websocket send.
        sent: list[str] = []

        class _Ws:
            async def send(self, message):
                sent.append(message)

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "is_connected", property(lambda self: True)
        )
        conn.connection = _Ws()
        conn._generate_salt()
        conn._token.token = "secret-jwt-123"

        with caplog.at_level(
            logging.DEBUG, logger="custom_components.loxone.pyloxone_api.connection"
        ):
            await conn.kill_token()

        assert len(sent) == 1
        assert sent[0].startswith("jdev/sys/enc/")
        assert "secret-jwt-123" not in sent[0]
        assert "secret-jwt-123" not in caplog.text
        assert "jdev/sys/killtoken/…" in caplog.text

    def test_coordinator_persists_token_without_logging_secret(self):
        """A refresh callback merges the new token into entry
        data, preserves unrelated data, and confirms persistence
        without putting the secret itself in the log.
        """
        from unittest.mock import patch

        from custom_components.loxone.coordinator import LoxoneCoordinator

        entry = SimpleNamespace(
            entry_id="entry-a",
            title="Test Miniserver",
            data={"existing_setting": "preserved"},
        )
        saved: list[dict] = []

        class _ConfigEntries:
            def async_update_entry(self, config_entry, *, data):
                saved.append(data)
                config_entry.data = data

        coordinator = object.__new__(LoxoneCoordinator)
        coordinator.config_entry = entry
        coordinator.hass = SimpleNamespace(
            config_entries=_ConfigEntries()
        )
        refreshed_token = {
            "token": "secret-token-value",
            "valid_until": 2_000_000_000,
            "hash_alg": "SHA256",
        }

        with patch("custom_components.loxone.coordinator._LOGGER.info") as info:
            coordinator._on_token_changed(refreshed_token)

        assert len(saved) == 1
        assert entry.data == {
            "existing_setting": "preserved",
            **refreshed_token,
        }
        assert info.called
        assert "secret-token-value" not in str(info.call_args)


class TestOutageTracking:
    """``_note_connection_lost`` / ``_note_connection_restored`` —
    one WARNING per outage, one INFO on restore.

    A single dropped connection may be noticed by the keepalive,
    the recv loop, and the supervisor at slightly different
    times. The ``_outage_active`` flag makes sure the user sees
    one "Connection lost" line and one "Connection restored"
    line, not three of each.
    """

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    def test_initial_state(self, conn):
        """Freshly constructed: not in an outage, not confirmed
        connected.
        """
        assert conn._outage_active is False
        assert conn._confirmed_connected is False

    def test_first_lost_logs_warning(self, conn):
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            conn._note_connection_lost("test reason")
        assert warn.called
        # The reason appears in the log.
        assert "test reason" in str(warn.call_args)
        # The flag is set.
        assert conn._outage_active is True

    def test_second_lost_during_same_outage_is_debug(self, conn):
        """A second call before restore must log at DEBUG, not
        WARNING — otherwise an outage would spam the log.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        conn._note_connection_lost("first")
        with patch.object(conn_mod._LOGGER, "warning") as warn:
            with patch.object(conn_mod._LOGGER, "debug") as debug:
                conn._note_connection_lost("second")
        # No second WARNING.
        assert not warn.called
        # A DEBUG was emitted.
        assert debug.called

    def test_restore_after_outage_logs_info(self, conn):
        """After a lost+restored cycle, the restore logs at
        INFO and clears the flag.
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        # ``_confirmed_connected`` is set by the first
        # successful connect in ``open()``; we set it manually
        # here because the test bypasses the real connect path.
        conn._confirmed_connected = True
        conn._note_connection_lost("first")
        with patch.object(conn_mod._LOGGER, "info") as info:
            conn._note_connection_restored()
        assert info.called
        assert "Connection restored" in str(info.call_args)
        assert conn._outage_active is False
        assert conn._confirmed_connected is True

    def test_restore_without_outage_is_silent(self, conn):
        """A restore call with no prior outage is a no-op.
        Common case: the very first ``_note_connection_restored``
        after ``open()`` succeeds (no outage in progress).
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        with patch.object(conn_mod._LOGGER, "info") as info:
            conn._note_connection_restored()
        assert not info.called
        # ``_confirmed_connected`` is NOT set by the helper
        # itself — that's the responsibility of the first
        # successful ``open()`` cycle. Subsequent outages will
        # see ``_confirmed_connected`` already True and will
        # announce a restore.
        assert conn._confirmed_connected is False

    def test_outage_lost_restored_lost_cycle(self, conn):
        """After a full lost→restored cycle, a second lost
        must again produce a WARNING (not just DEBUG).
        """
        from unittest.mock import patch

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        # First cycle.
        conn._confirmed_connected = True
        conn._note_connection_lost("first outage")
        conn._note_connection_restored()

        # Second outage.
        with patch.object(conn_mod._LOGGER, "warning") as warn:
            conn._note_connection_lost("second outage")
        assert warn.called
        assert "second outage" in str(warn.call_args)


class TestRunSupervisor:
    """``run()`` — bounded exponential-backoff supervisor.

    The supervisor owns the listen loop on the same
    :class:`LoxoneConnection` instance. On
    :attr:`RETRYABLE_SESSION_ERRORS` it closes, sleeps
    ``min(base_delay * 2^n, max_delay)`` with ±20% jitter,
    and retries. ``LoxoneUnauthorisedError`` propagates (no
    retry). ``close()`` ends the loop cleanly.
    """

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    @pytest.mark.asyncio
    async def test_run_exits_cleanly_on_shutdown(
        self, conn, monkeypatch
    ):
        """If ``start_listening`` returns without raising (the
        clean-shutdown path) ``run()`` returns without
        retrying.
        """
        calls: list[int] = []

        async def fake_start_listening(self, callback=None):
            calls.append(1)
            # Simulate the clean-shutdown path: return
            # without raising.
            return None

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        # ``start_listening`` would normally call ``open()``
        # which would need a session, so we pre-set
        # ``self.connection`` to satisfy the guard.
        from types import SimpleNamespace
        conn.connection = SimpleNamespace(
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
        )

        states: list[str] = []
        on_state = lambda s: states.append(s)

        await conn.run(on_state=on_state, base_delay=0.0, max_delay=0.0)
        # ``start_listening`` was called exactly once.
        assert len(calls) == 1
        # And we announced a "disconnected" state.
        assert "disconnected" in states

    @pytest.mark.asyncio
    async def test_run_retries_on_recoverable_error(
        self, conn, monkeypatch
    ):
        """``LoxoneConnectionError`` (a RETRYABLE_SESSION_ERRORS
        member) triggers an exponential-backoff retry.
        """
        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionError,
        )

        attempts: list[int] = []

        async def fake_start_listening(self, callback=None):
            attempts.append(len(attempts) + 1)
            # First two attempts fail, third one returns
            # cleanly. The supervisor should retry twice.
            if len(attempts) < 3:
                raise LoxoneConnectionError("transient")
            return None

        from types import SimpleNamespace
        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        # Bypass ``open()`` by pre-setting ``self.connection``.
        conn.connection = SimpleNamespace(
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
        )
        # Avoid the real ``close()`` (which would try to
        # touch the fake connection's ``.close()`` method).
        async def fake_close(self):
            return None
        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "close", fake_close
        )

        # Don't actually sleep between attempts.
        await conn.run(base_delay=0.0, max_delay=0.0)
        assert len(attempts) == 3

    @pytest.mark.asyncio
    async def test_run_propagates_unauthorised(
        self, conn, monkeypatch
    ):
        """``LoxoneUnauthorisedError`` must propagate, NOT
        retry. This is what makes a wrong-password config
        entry surface as a config-entry error instead of
        looping forever.
        """
        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        attempts: list[int] = []

        async def fake_start_listening(self, callback=None):
            attempts.append(1)
            raise LoxoneUnauthorisedError("simulated wrong password")

        from types import SimpleNamespace
        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        conn.connection = SimpleNamespace(
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
        )

        with pytest.raises(LoxoneUnauthorisedError):
            await conn.run(base_delay=0.0, max_delay=0.0)
        # Exactly one attempt — no retry.
        assert len(attempts) == 1

    @pytest.mark.asyncio
    async def test_run_signals_state_on_disconnect(
        self, conn, monkeypatch
    ):
        """``on_state("disconnected")`` is fired on a
        recoverable error before the backoff sleep.
        """
        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionError,
        )

        async def fake_start_listening(self, callback=None):
            raise LoxoneConnectionError("transient")

        from types import SimpleNamespace
        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        conn.connection = SimpleNamespace(
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
        )
        async def fake_close(self):
            return None
        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "close", fake_close
        )

        states: list[str] = []

        async def on_state(s):
            # Raise to bail out of the retry loop (otherwise
            # we'd back off forever).
            states.append(s)
            if len(states) >= 2:
                # We've seen a "disconnected" — break out of
                # the supervisor by triggering a clean
                # shutdown.
                conn._shutdown_event.set()

        # Bump base_delay so the second attempt doesn't fire
        # before we set the shutdown event.
        await conn.run(
            on_state=on_state, base_delay=0.01, max_delay=0.01
        )
        # We saw at least one "disconnected" signal.
        assert "disconnected" in states

    @pytest.mark.asyncio
    async def test_run_backoff_grows_exponentially(
        self, conn, monkeypatch
    ):
        """The sleep between attempt N and N+1 is
        ``min(base·2^(N-1), max_delay)`` ± 20%. With
        ``base_delay=0.1`` and ``max_delay=10``, the delays
        are 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 10, 10, ...
        """
        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionError,
        )

        attempts: list[int] = []

        async def fake_start_listening(self, callback=None):
            attempts.append(len(attempts) + 1)
            if len(attempts) >= 5:
                # Set the shutdown flag and return cleanly so
                # the supervisor exits the retry loop.
                conn._shutdown_event.set()
                return None
            raise LoxoneConnectionError("transient")

        # We expect 4 sleep calls — one between each of the
        # 4 failed attempts. The 5th attempt is the
        # clean-shutdown path, no sleep needed.
        # (4 attempts fail: sleeps 0.1, 0.2, 0.4, 0.8. Then
        # 5th attempt is clean-shutdown.)

        from types import SimpleNamespace
        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        conn.connection = SimpleNamespace(
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
        )

        # Capture ``asyncio.sleep`` calls inside the
        # connection module so we can assert the backoff
        # values without actually waiting.
        sleeps: list[float] = []
        original_sleep = conn_mod.asyncio.sleep

        async def _record_sleep(delay):
            sleeps.append(delay)
            return await original_sleep(0)

        conn_mod.asyncio.sleep = _record_sleep
        async def fake_close(self):
            return None
        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "close", fake_close
        )

        try:
            await conn.run(
                on_state=None, base_delay=0.1, max_delay=10.0
            )
        finally:
            conn_mod.asyncio.sleep = original_sleep

        # Four failures → four sleeps (the 5th attempt is
        # the clean-shutdown path, no sleep needed). The
        # first sleep is 0.1, then 0.2, 0.4, 0.8.
        # But because the function also does ``sleep(0)``
        # between attempts (the "yield so on_state runs"
        # call), there are extra ``0.0`` entries in the list.
        # Filter to the non-zero sleeps.
        non_zero = [s for s in sleeps if s > 0]
        assert len(non_zero) == 4
        expected = [0.1, 0.2, 0.4, 0.8]
        for actual, exp in zip(non_zero, expected):
            assert exp * 0.8 <= actual <= exp * 1.2, (
                f"sleep {actual} outside ±20% of {exp}"
            )


class TestRunSupervisorReconnect:
    """Regression test: the supervisor's retry loop must NOT
    be killed by its own ``_safe_close`` setting the shutdown
    event.

    Bug: ``close()`` sets ``_shutdown_event`` to signal
    "permanent close, don't come back". The supervisor's
    internal retry path used the same ``close()`` to clean
    up after a failed attempt, which also set the event —
    the next iteration of the retry loop then saw
    ``_shutdown_event.is_set()`` and exited instead of
    reconnecting. Symptom: a single transient drop killed
    the whole integration; ``send_websocket_command`` was
    called but no reconnect ever happened.

    Fix: ``close()`` takes a private ``_signal_shutdown`` flag
    (default True). The supervisor's ``_safe_close`` passes
    ``False``.
    """

    @pytest.mark.asyncio
    async def test_safe_close_does_not_set_shutdown_event(
        self, monkeypatch
    ):
        from custom_components.loxone.pyloxone_api.connection import (
            LoxoneConnection,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def fake_close(self, _signal_shutdown=True):
            self._closed = True
            if _signal_shutdown:
                self._shutdown_event.set()

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "close", fake_close
        )

        # Pre-condition.
        assert not conn._shutdown_event.is_set()

        await conn._safe_close()
        # ``_safe_close`` must NOT set the shutdown event —
        # the supervisor's retry loop checks this event to
        # decide whether to keep going.
        assert not conn._shutdown_event.is_set()
        # Unlike the public close, internal cleanup must also
        # leave the instance reusable by the next ``open()``.
        assert conn._closed is False

    @pytest.mark.asyncio
    async def test_close_does_set_shutdown_event(
        self, monkeypatch
    ):
        """Sanity check: the public ``close()`` still sets
        the shutdown event (the integration calls it from
        ``async_cleanup`` to mean "really stop now").
        """
        from custom_components.loxone.pyloxone_api.connection import (
            LoxoneConnection,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        async def fake_close(self, _signal_shutdown=True):
            # Honour the flag like the real close() does.
            if _signal_shutdown:
                self._shutdown_event.set()
            self._closed = True

        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "close", fake_close
        )

        assert not conn._shutdown_event.is_set()
        await conn.close()
        assert conn._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_run_retries_after_session_error(
        self, monkeypatch
    ):
        """The full regression scenario: a transient session
        error triggers a backoff sleep, then a retry that
        succeeds. The integration must end up running
        ``start_listening`` more than once.
        """
        from custom_components.loxone.pyloxone_api.connection import (
            LoxoneConnection,
        )
        from custom_components.loxone.pyloxone_api import (
            connection as conn_mod,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        # Pre-set the connection so ``start_listening``
        # doesn't try to ``open()`` and need a real
        # session.
        from types import SimpleNamespace
        conn.connection = SimpleNamespace(
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN")
        )

        start_listening_calls: list[int] = []

        async def fake_start_listening(self, callback=None):
            start_listening_calls.append(len(start_listening_calls) + 1)
            if len(start_listening_calls) == 1:
                # First attempt: fail with a recoverable
                # error.
                raise LoxoneConnectionError("transient")
            assert self._closed is False
            # Second attempt: clean-shutdown.
            return None

        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )

        # The fake close() honours the new flag the way
        # the real one does, so we can assert the shutdown
        # event stays clear between attempts.
        async def fake_close(self, _signal_shutdown=True):
            self._closed = True
            if _signal_shutdown:
                self._shutdown_event.set()

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "close", fake_close
        )

        await conn.run(base_delay=0.0, max_delay=0.0)

        # ``start_listening`` was called twice — once
        # failing, once succeeding. Before the fix, the
        # supervisor's internal close() set the shutdown
        # event and the second call never happened.
        assert len(start_listening_calls) == 2, (
            f"expected 2 start_listening calls (1 fail + "
            f"1 success), got {len(start_listening_calls)}"
        )


class TestManualTokenRefresh:
    """The manual token refresh operation reuses the same
    key-exchange/refresh sequence as automatic maintenance,
    waits for confirmation, and serializes concurrent calls.
    """

    @pytest.mark.asyncio
    async def test_refresh_requests_key_then_waits_for_token(self, monkeypatch):
        from custom_components.loxone.pyloxone_api.connection import (
            LoxoneConnection,
        )

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn._authenticated_event.set()
        conn._token.token = "existing-token"
        conn._key = "old-key"
        conn.connection = SimpleNamespace(
            protocol=SimpleNamespace(state=SimpleNamespace(name="OPEN")),
            state=SimpleNamespace(CLOSED="CLOSED", OPEN="OPEN", name="OPEN"),
        )
        sent: list[str] = []

        async def fake_send(self, command, encrypted=False):
            sent.append(command)
            assert encrypted is False
            self._key = "new-key"
            self._key_update_event.set()

        async def fake_refresh():
            conn._token.token = "updated-token"
            conn._token.valid_until = 2_000_000_000
            conn._token_refresh_event.set()

        monkeypatch.setattr(LoxoneConnection, "_send_text_command", fake_send)
        conn._refresh_token = fake_refresh

        result = await conn.async_refresh_token()

        assert sent == ["jdev/sys/getkey"]
        assert result["token"] == "updated-token"
        assert conn._key_update_event is None

    @pytest.mark.asyncio
    async def test_refresh_fails_before_authentication(self):
        from custom_components.loxone.pyloxone_api.connection import (
            LoxoneConnection,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneTokenError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        with pytest.raises(LoxoneTokenError, match="before authentication"):
            await conn.async_refresh_token()


class TestRefreshTokenServiceRouting:
    """The integration-wide service must dispatch to only the
    selected config entry, even when several entries are loaded.
    """

    @pytest.mark.asyncio
    async def test_service_refreshes_only_selected_entry(self):
        from types import SimpleNamespace

        from custom_components.loxone import _async_handle_refresh_token
        from custom_components.loxone.const import DOMAIN

        calls: list[str] = []

        class _Api:
            def __init__(self, entry_id):
                self.entry_id = entry_id

            async def async_refresh_token(self):
                calls.append(self.entry_id)

        def _coordinator(entry_id):
            return SimpleNamespace(
                config_entry=SimpleNamespace(
                    entry_id=entry_id, domain=DOMAIN, title=f"Loxone {entry_id}"
                ),
                api=_Api(entry_id),
            )

        hass = SimpleNamespace(
            data={DOMAIN: {"entry-a": _coordinator("entry-a"),
                           "entry-b": _coordinator("entry-b")}}
        )
        call = SimpleNamespace(data={"config_entry_id": "entry-b"})

        await _async_handle_refresh_token(hass, call)
        assert calls == ["entry-b"]

    @pytest.mark.asyncio
    async def test_service_rejects_unloaded_or_invalid_entry(self):
        from types import SimpleNamespace

        from homeassistant.exceptions import HomeAssistantError

        from custom_components.loxone import _async_handle_refresh_token
        from custom_components.loxone.const import DOMAIN

        hass = SimpleNamespace(data={DOMAIN: {}})
        call = SimpleNamespace(data={"config_entry_id": "not-loaded"})

        with pytest.raises(HomeAssistantError, match="not loaded"):
            await _async_handle_refresh_token(hass, call)

    @pytest.mark.asyncio
    async def test_global_service_registers_once(self, hass):
        from custom_components.loxone import async_setup
        from custom_components.loxone.const import (
            DOMAIN,
            SERVICE_REFRESH_TOKEN,
        )

        assert await async_setup(hass, {})
        assert await async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, SERVICE_REFRESH_TOKEN)


class TestLoxoneTokenExpiryFormatting:
    def test_formats_loxone_timestamp_and_remaining_duration(self):
        import datetime

        from custom_components.loxone.pyloxone_api.connection import (
            _format_loxone_token_expiration,
        )
        from custom_components.loxone.pyloxone_api.loxone_token import (
            LOXONE_EPOCH,
        )

        now = datetime.datetime(2026, 10, 8, 21, 57, 32)
        valid_until = 560_765_254

        formatted = _format_loxone_token_expiration(valid_until, now)

        assert formatted == "2026-10-09 08:07:34; in 0d 10h 10m 2s"
        assert LOXONE_EPOCH + datetime.timedelta(seconds=valid_until) == (
            datetime.datetime(2026, 10, 9, 8, 7, 34)
        )

    def test_formats_expired_token_as_time_ago(self):
        import datetime

        from custom_components.loxone.pyloxone_api.connection import (
            _format_loxone_token_expiration,
        )
        from custom_components.loxone.pyloxone_api.loxone_token import (
            LOXONE_EPOCH,
        )

        now = LOXONE_EPOCH + datetime.timedelta(seconds=120)

        assert _format_loxone_token_expiration(60, now) == (
            "2009-01-01 00:01:00; ago 0d 0h 1m 0s"
        )


class _BlockingWebsocket(_FakeWebsocket):
    """A peer that never sends a frame (simulated stale connection).

    ``async for`` blocks forever, which is what a half-open TCP
    connection looks like from the receiving side: no frames, no
    error, and our keepalive writes still succeed.
    """

    async def __anext__(self):
        await asyncio.sleep(3600)


class _KeepaliveWebsocket(_FakeWebsocket):
    """A peer that keeps sending 8-byte KEEPALIVE headers forever."""

    async def __anext__(self):
        await asyncio.sleep(0.005)
        # Loxone binary header for a bodyless KEEPALIVE:
        # cBinType=0x03, cIdentifier=6 (KEEPALIVE), cInfo/cReserved=0,
        # 32-bit payload length = 0.
        return b"\x03\x06\x00\x00\x00\x00\x00\x00"


class TestReceiveWatchdog:
    """``WEBSOCKET_READ_TIMEOUT`` — stale-connection detection.

    ``_build_websocket_options`` disables the ``websockets`` library's
    ping/pong liveness check, so the only inbound-liveness signal is
    the Loxone keepalive frame. A connection that stops delivering
    frames must be torn down and reconnected instead of lingering
    until the TCP retransmit timeout fires.
    """

    @pytest.fixture
    def conn(self):
        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        # ``start_listening()`` refuses to run without a session key.
        conn._session_key = b"AAAA"
        return conn

    def _patch_timers(self, monkeypatch):
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        monkeypatch.setattr(conn_mod, "KEEP_ALIVE_PERIOD", 0.01)
        monkeypatch.setattr(conn_mod, "WEBSOCKET_READ_TIMEOUT", 0.05)

    @pytest.mark.asyncio
    async def test_stale_connection_raises_after_read_timeout(
        self, monkeypatch, conn
    ):
        """No inbound frame for WEBSOCKET_READ_TIMEOUT →
        ``LoxoneConnectionError`` + one "connection lost" warning.
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionError,
        )

        self._patch_timers(monkeypatch)
        conn.connection = _BlockingWebsocket()

        with pytest.raises(LoxoneConnectionError):
            await asyncio.wait_for(conn.start_listening(), timeout=5)

        assert conn._outage_active is True

    @pytest.mark.asyncio
    async def test_frames_reset_the_watchdog(
        self, monkeypatch, conn
    ):
        """A peer that keeps sending frames does NOT trigger the
        watchdog, and the recv loop refreshes ``_last_frame_time``.
        """
        self._patch_timers(monkeypatch)
        conn.connection = _KeepaliveWebsocket()

        task = asyncio.create_task(conn.start_listening())
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert conn._outage_active is False
        import time

        assert time.monotonic() - conn._last_frame_time < 0.05

    @pytest.mark.asyncio
    async def test_open_resets_last_frame_time(self, monkeypatch):
        """``open()`` must reset the watchdog: a slow bootstrap
        (apiKey / LoxAPP3 / publicKey) must not look like a stale
        connection to the first keepalive cycle.
        """
        import time

        from custom_components.loxone.pyloxone_api import connection as conn_mod

        fake_ws = _FakeWebsocket()

        async def fake_connect(*args, **kwargs):
            return fake_ws

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        from Crypto.PublicKey import RSA

        rsa_key = RSA.generate(2048)
        session = _FakeHttpSession(rsa_key.publickey().export_key().decode())

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        # Pretend a previous attempt went stale a long time ago.
        conn._last_frame_time = time.monotonic() - 10_000

        await conn.open(session=session)

        assert time.monotonic() - conn._last_frame_time < 5

    @staticmethod
    def _authwithtoken_reply(code: int):
        return parse_message(
            json.dumps(
                {
                    "LL": {
                        "control": "authwithtoken/hash/user",
                        "code": str(code),
                        "value": {"validUntil": 500000000},
                    }
                }
            ),
            MessageType.TEXT,
        )

    @pytest.mark.asyncio
    async def test_connected_state_only_after_login(self, monkeypatch):
        """"connected" is signalled through the callback ``run()``
        published on ``self._on_state`` once the session has logged
        in — not when the websocket opens (a failed login would make
        entities flip to available and back).
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        fake_ws = _FakeWebsocket()

        async def fake_connect(*args, **kwargs):
            return fake_ws

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        from Crypto.PublicKey import RSA

        rsa_key = RSA.generate(2048)
        session = _FakeHttpSession(rsa_key.publickey().export_key().decode())

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        states = []
        conn._on_state = states.append

        await conn.open(session=session)
        assert states == []

        # A rejected cached token is not a login.
        await conn._websocket_event(self._authwithtoken_reply(401))
        assert states == []
        assert not conn._authenticated_event.is_set()

        await conn._websocket_event(self._authwithtoken_reply(200))
        assert states == ["connected"]
        assert conn._authenticated_event.is_set()

    def test_default_read_timeout_is_three_keepalives(self):
        """The default timeout equals three missed keepalives."""
        from custom_components.loxone.pyloxone_api.const import (
            KEEP_ALIVE_PERIOD,
            WEBSOCKET_READ_TIMEOUT,
        )

        assert WEBSOCKET_READ_TIMEOUT == 3 * KEEP_ALIVE_PERIOD


class TestAuthEscalation:
    """401/4003 must reach the ``run()`` supervisor (P2/P3).

    Before: ``_check_auth_response`` raised inside the auth handlers,
    where the enclosing ``except Exception`` logged it away — and the
    handlers themselves run as fire-and-forget tasks. A wrong password
    therefore produced a silent retry loop with unavailable entities
    instead of a config-entry reload.
    """

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    def test_401_records_auth_failure_and_raises(self, conn):
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        with pytest.raises(LoxoneUnauthorisedError):
            conn._check_auth_response(SimpleNamespace(code=401), "gettoken")
        assert isinstance(conn._auth_failure, LoxoneUnauthorisedError)

    def test_auth_failure_starts_unset(self, conn):
        assert conn._auth_failure is None

    @pytest.mark.asyncio
    async def test_getkey_401_propagates_from_websocket_event(self, conn):
        """A 401 in a ``getkey`` response escapes ``_websocket_event``
        instead of being swallowed by the handler's ``except``.
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        message = TextMessage(
            '{"LL": {"code": 401, "control": "jdev/sys/getkey", "value": ""}}'
        )
        with pytest.raises(LoxoneUnauthorisedError):
            await conn._websocket_event(message)

    @pytest.mark.asyncio
    async def test_auth_failure_is_raised_by_recv_loop(self, monkeypatch, conn):
        """The recv loop surfaces a recorded auth failure on the next
        inbound frame, so the ``run()`` supervisor sees it.
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        message = TextMessage(
            '{"LL": {"code": 401, "control": "jdev/sys/getkey", "value": ""}}'
        )
        # Fire-and-forget, exactly like ``_dispatch_body`` does it.
        conn._spawn_task(conn._websocket_event(message), name="loxone.event")
        # The text message sets the flag; the recv loop re-raises it.
        for _ in range(5):
            if conn._auth_failure is not None:
                break
            await asyncio.sleep(0)

        assert conn._auth_failure is not None

        conn.connection = _KeepaliveWebsocket()
        conn._session_key = b"AAAA"
        with pytest.raises(LoxoneUnauthorisedError):
            await asyncio.wait_for(conn.start_listening(), timeout=5)

    @pytest.mark.asyncio
    async def test_run_propagates_auth_failure_without_retry(self, monkeypatch):
        """``run()`` must not retry a credential rejection."""
        from custom_components.loxone.pyloxone_api import connection as conn_mod
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        attempts = []

        async def fake_start_listening(self, callback=None):
            attempts.append(1)
            raise LoxoneUnauthorisedError("bad credentials")

        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        states = []
        with pytest.raises(LoxoneUnauthorisedError):
            await conn.run(on_state=states.append, base_delay=0, max_delay=0)

        assert len(attempts) == 1
        assert states == ["failed"]

    @pytest.mark.asyncio
    async def test_run_propagates_escalated_auth_without_retry(
        self, monkeypatch
    ):
        """After TOKEN_REFRESH_MAX_FAILURES failed cycles ``run()``
        stops retrying instead of looping forever.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneAuthEscalatedError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        attempts = []

        async def fake_start_listening(self, callback=None):
            attempts.append(1)
            raise LoxoneAuthEscalatedError("gave up")

        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        states = []
        with pytest.raises(LoxoneAuthEscalatedError):
            await conn.run(on_state=states.append, base_delay=0, max_delay=0)

        assert len(attempts) == 1
        assert states == ["failed"]

    @pytest.mark.asyncio
    async def test_run_still_retries_plain_token_error(self, monkeypatch):
        """A ``LoxoneTokenError`` stays retryable — it is the expected
        first leg of the token-expiry self-heal.
        """
        from custom_components.loxone.pyloxone_api import connection as conn_mod
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneTokenError,
        )

        conn = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        attempts = []

        async def fake_start_listening(self, callback=None):
            attempts.append(len(attempts))
            if len(attempts) < 3:
                raise LoxoneTokenError("token expired")
            return None

        monkeypatch.setattr(
            conn_mod.LoxoneConnection,
            "start_listening",
            fake_start_listening,
        )
        conn.connection = _FakeWebsocket()

        await conn.run(base_delay=0, max_delay=0)

        assert len(attempts) == 3

    def test_retryable_errors_are_explicit(self):
        """No blanket ``LoxoneException`` retry, and neither the
        credential rejection nor the escalation is swallowed.
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneAuthEscalatedError,
            LoxoneException,
            LoxoneTokenError,
            LoxoneUnauthorisedError,
        )

        retryable = LoxoneConnection.RETRYABLE_SESSION_ERRORS
        assert not issubclass(LoxoneAuthEscalatedError, retryable)
        assert not issubclass(LoxoneUnauthorisedError, retryable)
        # Token errors stay retryable (token-expiry self-heal), but the
        # blanket base class is gone.
        assert issubclass(LoxoneTokenError, retryable)
        assert LoxoneException not in retryable

    @pytest.mark.asyncio
    async def test_refresh_401_unblocks_awaiting_refresh(self, conn):
        """The refresh handler unblocks an ``async_refresh_token``
        caller with the auth error instead of leaving it hanging.
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        conn._authenticated_event.set()
        conn._token.token = "existing-token"
        conn._token.key = "key"
        conn._token.hash_alg = "SHA1"
        conn._token.valid_until = 999999999

        refresh_message = TextMessage(
            '{"LL": {"code": 401, "control": "jdev/sys/refreshjwt", "value": ""}}'
        )

        with pytest.raises(LoxoneUnauthorisedError):
            await conn._websocket_event(refresh_message)

        assert conn._token_refresh_event.is_set()
        assert isinstance(conn._token_refresh_error, LoxoneUnauthorisedError)


class TestCoordinatorTokenCleanup:
    """``async_cleanup`` must not kill the persisted token (P4)."""

    @pytest.mark.asyncio
    async def test_cleanup_does_not_kill_token_by_default(self):
        from custom_components.loxone.coordinator import LoxoneCoordinator

        calls = []

        class _FakeApi:
            async def kill_token(self):
                calls.append("kill")

            async def close(self):
                calls.append("close")

        coordinator = LoxoneCoordinator.__new__(LoxoneCoordinator)
        coordinator.listeners = []
        coordinator.api = _FakeApi()

        await coordinator.async_cleanup()

        assert calls == ["close"]

    @pytest.mark.asyncio
    async def test_cleanup_kills_token_on_request(self):
        from custom_components.loxone.coordinator import LoxoneCoordinator

        calls = []

        class _FakeApi:
            async def kill_token(self):
                calls.append("kill")

            async def close(self):
                calls.append("close")

        coordinator = LoxoneCoordinator.__new__(LoxoneCoordinator)
        coordinator.listeners = []
        coordinator.api = _FakeApi()

        await coordinator.async_cleanup(kill_token=True)

        assert calls == ["kill", "close"]

    @pytest.mark.asyncio
    async def test_remove_entry_kills_token_while_connected(self):
        """Removing the entry invalidates the token — but only while
        the websocket is still open; after unload it is a no-op and
        the token simply expires.
        """
        from types import SimpleNamespace as NS

        from custom_components.loxone import async_remove_entry

        calls = []

        class _FakeApi:
            is_connected = True

            async def kill_token(self):
                calls.append("kill")

        coordinator = NS(
            config_entry=NS(entry_id="abc"),
            api=_FakeApi(),
        )
        hass = NS(data={"loxone": {"abc": coordinator}})

        await async_remove_entry(hass, NS(entry_id="abc"))

        assert calls == ["kill"]

    @pytest.mark.asyncio
    async def test_remove_entry_skips_kill_when_disconnected(self):
        from types import SimpleNamespace as NS

        from custom_components.loxone import async_remove_entry

        calls = []

        class _FakeApi:
            is_connected = False

            async def kill_token(self):
                calls.append("kill")

        coordinator = NS(
            config_entry=NS(entry_id="abc"),
            api=_FakeApi(),
        )
        hass = NS(data={"loxone": {"abc": coordinator}})

        await async_remove_entry(hass, NS(entry_id="abc"))

        assert calls == []


class TestEntityAvailability:
    """Entities follow the connection state (P5)."""

    def test_entity_inherits_availability_property(self):
        from custom_components.loxone import LoxoneEntity

        # The base class must define an ``available`` property that
        # ANDs the entity flag with the connection state; the sensor
        # override must consult the same helper.
        assert isinstance(LoxoneEntity.available, property)
        assert hasattr(LoxoneEntity, "_connection_available")

    def test_connection_available_defaults_to_true_without_coordinator(self):
        from custom_components.loxone import LoxoneEntity

        entity = LoxoneEntity.__new__(LoxoneEntity)
        entity._attr_available = True
        # No ``hass``/registry entry → must not block availability.
        entity.hass = SimpleNamespace(data={})
        assert entity._connection_available() is True

    def test_connection_unavailable_marks_entity_unavailable(self):
        from types import SimpleNamespace as NS

        from custom_components.loxone import LoxoneEntity

        class _Coordinator:
            connection_available = False

        entity = LoxoneEntity.__new__(LoxoneEntity)
        entity._attr_available = True
        entity.registry_entry = NS(config_entry_id="abc")
        entity.hass = NS(data={"loxone": {"abc": _Coordinator()}})

        assert entity.available is False

    def test_connection_available_with_value(self):
        from types import SimpleNamespace as NS

        from custom_components.loxone import LoxoneEntity

        class _Coordinator:
            connection_available = True

        entity = LoxoneEntity.__new__(LoxoneEntity)
        entity._attr_available = True
        entity.registry_entry = NS(config_entry_id="abc")
        entity.hass = NS(data={"loxone": {"abc": _Coordinator()}})

        assert entity.available is True


class TestSaltRotationLock:
    """``_send_text_command`` must serialize the salt decision (3.3).

    The send path is concurrent: ``_process_message`` spawns one
    fire-and-forget task per queued message, and ``open()`` / token
    refresh call ``_send_text_command`` directly. The salt
    (``_salt``) plus its usage counters are shared instance state, so
    deciding and generating must happen atomically — otherwise a
    sender can build its ``nextSalt/`` command against a salt another
    sender has already rotated past.

    Two contract points are guarded here:

    * the decision runs *under* ``_salt_lock`` (fails if the
      ``async with`` is dropped),
    * the lock is released before the AES work and the websocket send
      (fails if someone wraps the whole send in the lock and starts
      serializing I/O).
    """

    class _RecordingWebsocket(_FakeWebsocket):
        """``_FakeWebsocket`` that records the payloads it is given."""

        def __init__(self, on_send=None):
            self.sent: list[str] = []
            self._on_send = on_send

        async def send(self, *args, **kwargs):
            if self._on_send is not None:
                self._on_send(*args)
            self.sent.append(args[0] if args else "")

    @staticmethod
    def _plaintext(conn, sent: str) -> str:
        """Undo ``jdev/sys/enc`` + percent-encoding on a recorded send."""
        prefix = "jdev/sys/enc/"
        assert sent.startswith(prefix), sent
        # ``_decrypt`` expects the raw base64, so undo the URL quoting
        # that ``_send_text_command`` applied on the way out.
        quoted = sent[len(prefix) :]
        return conn._decrypt(prefix + urllib.parse.unquote(quoted)).decode("utf-8")

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    @pytest.mark.asyncio
    async def test_salt_lock_exists_and_starts_released(self, conn):
        assert isinstance(conn._salt_lock, asyncio.Lock)
        assert not conn._salt_lock.locked()

    @pytest.mark.asyncio
    async def test_salt_decision_runs_under_lock(self, conn):
        """The decision + rotation must execute while the lock is held."""
        conn.connection = self._RecordingWebsocket()
        observed: list[bool] = []

        def spy():
            observed.append(conn._salt_lock.locked())
            return True  # force a rotation on this send

        conn._new_salt_needed = spy
        await conn._send_text_command("jdev/sys/hello", encrypted=True)

        assert observed == [True], "salt decision ran without _salt_lock"
        assert conn._salt, "the forced rotation must have produced a salt"
        assert not conn._salt_lock.locked(), "lock must be released again"

    @pytest.mark.asyncio
    async def test_lock_released_before_aes_and_send(self, conn, monkeypatch):
        """The critical section must stop before AES and websocket I/O."""
        observed: dict[str, bool] = {}

        conn.connection = self._RecordingWebsocket(
            on_send=lambda *_: observed.update(send_locked=conn._salt_lock.locked())
        )

        def spy():
            observed["decision_locked"] = conn._salt_lock.locked()
            return True

        conn._new_salt_needed = spy

        import custom_components.loxone.pyloxone_api.connection as connection_module

        real_aes = connection_module.AES

        class _ProbeAES:
            """Proxy that records whether the lock was held during ``AES.new``."""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def new(self, *args, **kwargs):
                observed.setdefault("aes_locked", conn._salt_lock.locked())
                return self._real.new(*args, **kwargs)

        monkeypatch.setattr(connection_module, "AES", _ProbeAES(real_aes))

        await conn._send_text_command("jdev/sys/hello", encrypted=True)

        assert observed["decision_locked"] is True
        assert observed["aes_locked"] is False, "AES must run outside the lock"
        assert observed["send_locked"] is False, "send must run outside the lock"

    @pytest.mark.asyncio
    async def test_plain_commands_bypass_the_salt_state(self, conn):
        """Unencrypted commands never touch the salt or the lock."""
        conn.connection = self._RecordingWebsocket()

        def boom():
            raise AssertionError("plain commands must not consult the salt")

        conn._new_salt_needed = boom
        await conn._send_text_command("jdev/sys/plain", encrypted=False)

        assert conn.connection.sent == ["jdev/sys/plain"]
        assert not conn._salt_lock.locked()

    @pytest.mark.asyncio
    async def test_dead_connection_does_not_rotate_the_salt(self, conn):
        """A command that provably cannot be sent must not burn a rotation.

        The connection check now runs before the salt decision, so a
        dead socket cannot advance ``_salt`` past the Miniserver's
        (nor spend the AES work).
        """
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionClosedOk,
        )

        conn.connection = None
        conn._generate_salt()
        conn._salt_used_count = 10_000  # would trip the rotation threshold
        before = (conn._salt, conn._salt_used_count, conn._salt_time_stamp)

        with pytest.raises(LoxoneConnectionClosedOk):
            await conn._send_text_command("jdev/sys/hello", encrypted=True)

        assert (conn._salt, conn._salt_used_count, conn._salt_time_stamp) == before, (
            "the salt state must be untouched when the send is skipped"
        )

    @pytest.mark.asyncio
    async def test_concurrent_rotations_stay_chained(self, conn):
        """Parallel encrypted sends must hand the salt on, never skip."""
        conn.connection = self._RecordingWebsocket()
        conn._generate_salt()  # known starting point
        start_salt = conn._salt
        # Force a rotation for every send so all 20 tasks race for it.
        conn._new_salt_needed = lambda: True

        await asyncio.gather(*(conn._send_text_command(f"jdev/sys/{i}", encrypted=True) for i in range(20)))

        plaintexts = [self._plaintext(conn, s) for s in conn.connection.sent]
        assert len(plaintexts) == 20
        # Every payload must be a rotation in the nextSalt/<old>/<new>/<cmd>\0 form.
        pairs = []
        for text in plaintexts:
            parts = text.rstrip("\x00").split("/")
            assert parts[0] == "nextSalt", text
            pairs.append((parts[1], parts[2]))

        # old of the first rotation is the salt we started with, and each
        # rotation's new salt is the next rotation's old salt.
        assert pairs[0][0] == start_salt
        assert all(pairs[i][1] == pairs[i + 1][0] for i in range(len(pairs) - 1))
        assert pairs[-1][1] == conn._salt

    @pytest.mark.asyncio
    async def test_rotation_still_follows_use_count(self, conn, monkeypatch):
        """The lock must not shift *when* a rotation is triggered."""
        import custom_components.loxone.pyloxone_api.connection as connection_module

        monkeypatch.setattr(connection_module, "SALT_MAX_USE_COUNT", 3)
        conn.connection = self._RecordingWebsocket()
        conn._generate_salt()
        first_salt = conn._salt

        for i in range(4):
            await conn._send_text_command(f"cmd/{i}", encrypted=True)

        plaintexts = [self._plaintext(conn, s) for s in conn.connection.sent]
        kinds = [text.split("/")[0] for text in plaintexts]
        # Uses 1..3 stay on the current salt, use 4 trips over the threshold.
        assert kinds == ["salt", "salt", "salt", "nextSalt"]
        # The rotation carries the previously used salt and installs a new one.
        assert plaintexts[3].rstrip("\x00").split("/")[1] == first_salt
        assert conn._salt != first_salt


class TestGetvisusaltReleasesOneCommand:
    """A ``getvisusalt`` reply belongs to exactly one secure command.

    Previously one successful reply drained the whole queue, so a
    command whose own request had failed ran together with the next
    secure command (e.g. a failed "open gate" executing with a later
    "disarm alarm").
    """

    @staticmethod
    def _reply(code: int) -> str:
        return json.dumps(
            {
                "LL": {
                    "control": "jdev/sps/getvisusalt/user",
                    "code": str(code),
                    "value": {
                        "key": "aa" * 32,
                        "salt": "bb" * 16,
                        "hashAlg": "SHA1",
                    },
                }
            }
        )

    @pytest.mark.asyncio
    async def test_failed_reply_drops_its_command(self):
        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn._secured_queue.append(SecuredCommand("open-gate", "pulse", "1234"))
        conn._secured_queue.append(SecuredCommand("disarm", "off", "1234"))

        await conn._websocket_event(
            parse_message(self._reply(500), MessageType.TEXT)
        )
        # The failed reply consumed "open-gate" without sending it.
        assert [c.device_uuid for c in conn._secured_queue] == ["disarm"]
        assert conn._message_queue.qsize() == 0

        await conn._websocket_event(
            parse_message(self._reply(200), MessageType.TEXT)
        )
        assert conn._secured_queue == deque()
        assert conn._message_queue.qsize() == 1
        assert conn._message_queue.get_nowait().command.endswith("/disarm/off")

    @pytest.mark.asyncio
    async def test_successful_reply_releases_only_one_command(self):
        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn._secured_queue.append(SecuredCommand("dev-1", "on", "1234"))
        conn._secured_queue.append(SecuredCommand("dev-2", "on", "1234"))

        await conn._websocket_event(
            parse_message(self._reply(200), MessageType.TEXT)
        )

        assert conn._message_queue.qsize() == 1
        assert conn._message_queue.get_nowait().command.endswith("/dev-1/on")
        assert [c.device_uuid for c in conn._secured_queue] == ["dev-2"]


class TestRefreshTokenCommand:
    """``_refresh_token`` builds ``…/{tokenHash}/{user}`` for both the
    legacy (< 10.2) and the JWT command.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("version", "prefix"),
        [([10, 1], "jdev/sys/refreshtoken/"), ([12, 0], "jdev/sys/refreshjwt/")],
    )
    async def test_refresh_command_path(self, monkeypatch, version, prefix):
        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn.miniserver_version = version
        monkeypatch.setattr(conn, "_hash_token", lambda: "abc123")

        await conn._refresh_token()

        item = conn._message_queue.get_nowait()
        assert item.command == f"{prefix}abc123/user"
        assert item.flag is True


class TestReconnectResetsAuthentication:
    """A new websocket starts unauthenticated, so the token refresh
    must wait for that session's login again.
    """

    @pytest.fixture
    def fake_http_session(self):
        from Crypto.PublicKey import RSA

        rsa_key = RSA.generate(2048)
        return _FakeHttpSession(rsa_key.publickey().export_key().decode())

    @pytest.mark.asyncio
    async def test_new_websocket_clears_authenticated_event(
        self, monkeypatch, fake_http_session
    ):
        from custom_components.loxone.pyloxone_api import connection as conn_mod

        async def fake_connect(*args, **kwargs):
            return _FakeWebsocket()

        monkeypatch.setattr(conn_mod.wslib, "connect", fake_connect)

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        await conn.open(session=fake_http_session, connect_websocket=False)
        # Previous session had logged in.
        conn._authenticated_event.set()

        await conn._connect_websocket()

        assert not conn._authenticated_event.is_set()

    @pytest.mark.asyncio
    async def test_manual_refresh_refused_before_login(self):
        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn._token.token = "old-token"
        conn._authenticated_event.clear()

        with pytest.raises(Exception, match="(?i)authenticat"):
            await conn.async_refresh_token(timeout=0.1)


class TestFatalCloseCodes:
    """Close codes 4003 (blocked) and 4006 (user disabled) are not
    retried: reconnecting cannot succeed, and while blocked every
    attempt can extend the block.
    """

    @staticmethod
    def _closed(code: int):
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        return ConnectionClosedError(Close(code, ""), None)

    @pytest.mark.parametrize("code", [4003, 4006])
    def test_fatal_codes_raise_unauthorised(self, code):
        from custom_components.loxone.pyloxone_api.connection import (
            _raise_if_fatal_close,
        )
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        with pytest.raises(LoxoneUnauthorisedError, match=str(code)):
            _raise_if_fatal_close(self._closed(code))

    @pytest.mark.parametrize("code", [1006, 1011, 4007, 4008])
    def test_other_codes_stay_retryable(self, code):
        from custom_components.loxone.pyloxone_api.connection import (
            _raise_if_fatal_close,
        )

        _raise_if_fatal_close(self._closed(code))  # must not raise

    @pytest.mark.asyncio
    async def test_blocked_on_key_exchange_is_not_retried(self):
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        closed = self._closed(4003)

        class _BlockedWebsocket(_FakeWebsocket):
            async def send(self, *args, **kwargs):
                raise closed

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn.connection = _BlockedWebsocket()
        conn._session_key = b"fake-session-key"

        with pytest.raises(LoxoneUnauthorisedError):
            await conn.start_listening()

        # run() lets it through instead of retrying.
        assert not issubclass(
            LoxoneUnauthorisedError, LoxoneConnection.RETRYABLE_SESSION_ERRORS
        )


class TestTokenSelfHealLogging:
    """The token-expiry self-heal (authwithtoken 401 -> reconnect) is
    expected control flow and must not log an ERROR.
    """

    @pytest.mark.asyncio
    async def test_reconnect_request_raises_token_error_without_error_log(
        self, caplog
    ):
        import logging

        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneTokenError,
        )

        class _OpenWebsocket(_FakeWebsocket):
            async def __anext__(self):
                await asyncio.Event().wait()  # stays open

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn.connection = _OpenWebsocket()
        conn._session_key = b"fake-session-key"
        # What the authwithtoken 401 handler does.
        conn._reconnect_event.set()

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(LoxoneTokenError, match="re-authenticate"):
                await asyncio.wait_for(conn.start_listening(), timeout=5)

        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


class TestRefreshUnauthorisedEndsSession:
    """A 401 on the token refresh must end the session at once, not be
    counted as one of TOKEN_REFRESH_MAX_FAILURES ordinary failures.
    """

    @pytest.mark.asyncio
    async def test_refresh_401_is_not_retried(self, monkeypatch):
        from custom_components.loxone.pyloxone_api import connection as conn_mod
        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneUnauthorisedError,
        )

        class _OpenWebsocket(_FakeWebsocket):
            async def __anext__(self):
                await asyncio.Event().wait()  # stays open

        calls = 0

        async def rejected_refresh(self, timeout: float = 30.0):
            nonlocal calls
            calls += 1
            raise LoxoneUnauthorisedError("refreshjwt: unauthorised (code 401)")

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "async_refresh_token", rejected_refresh
        )

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn.connection = _OpenWebsocket()
        conn._session_key = b"fake-session-key"
        conn._token.token = "token"
        conn._token.valid_until = 1  # long expired -> refresh after 1 s
        conn._authenticated_event.set()

        with pytest.raises(LoxoneUnauthorisedError):
            await asyncio.wait_for(conn.start_listening(), timeout=10)

        assert calls == 1


class TestOutageLogging:
    """While the Miniserver is unreachable, reconnect attempts must not
    log an ERROR (with traceback) each time; ``run()`` reports the
    outage once as a WARNING.
    """

    class _UnreachableSession:
        closed = False

        def get(self, url, **kwargs):
            import aiohttp

            raise aiohttp.ClientConnectionError("Cannot connect to host")

    @pytest.mark.asyncio
    async def test_unreachable_miniserver_logs_no_error(self, monkeypatch, caplog):
        import logging

        from custom_components.loxone.pyloxone_api import connection as conn_mod

        original = conn_mod.LoxoneConnection._get_with_retry

        async def single_try(self, url, connector, **kwargs):
            return await original(self, url, connector, max_tries=1)

        monkeypatch.setattr(conn_mod.LoxoneConnection, "_get_with_retry", single_try)

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ConnectionError):
                await conn.open(session=self._UnreachableSession())

        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    @pytest.mark.asyncio
    async def test_network_drop_in_recv_loop_logs_no_error(self, caplog):
        import logging

        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        from custom_components.loxone.pyloxone_api.exceptions import (
            LoxoneConnectionError as LoxoneConnectionError_,
        )

        dropped = ConnectionClosedError(Close(1006, ""), None)

        class _DroppingWebsocket(_FakeWebsocket):
            async def __anext__(self):
                raise dropped

        conn = LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )
        conn.connection = _DroppingWebsocket()
        conn._session_key = b"fake-session-key"

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(LoxoneConnectionError_):
                await asyncio.wait_for(conn.start_listening(), timeout=5)

        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        lost = [r for r in caplog.records if "Connection lost" in r.getMessage()]
        assert len(lost) == 1 and lost[0].levelno == logging.WARNING


class TestShutdownRaces:
    """A real ``close()`` must stick, and stale queued commands must not
    leak into the next session.
    """

    @staticmethod
    def _conn():
        return LoxoneConnection(
            host="192.0.2.1", username="user", password="password", port=8080
        )

    @pytest.mark.asyncio
    async def test_close_during_safe_close_still_signals_shutdown(self):
        conn = self._conn()
        conn._closed = True  # a supervisor _safe_close() is in progress

        await conn.close()

        assert conn._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_close_during_bootstrap_is_not_undone(self):
        """``close()`` while ``open()`` was still bootstrapping: the
        socket opened afterwards is closed, nothing is listened on.
        """
        closed = []

        class _Ws(_FakeWebsocket):
            async def send(self, *args, **kwargs):
                raise AssertionError("must not send after close()")

            async def close(self, *args, **kwargs):
                closed.append(True)

        conn = self._conn()
        conn._session_key = b"fake-session-key"
        conn._shutdown_event.set()  # close() ran during open()
        conn.connection = _Ws()  # socket open() created anyway

        await asyncio.wait_for(conn.start_listening(), timeout=5)

        assert closed == [True]
        assert conn.connection is None
        assert conn._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_stale_commands_are_dropped_at_session_start(self, caplog):
        import logging

        sent: list[str] = []

        class _Ws(_FakeWebsocket):
            async def send(self, message, *args, **kwargs):
                sent.append(message)

        conn = self._conn()
        conn._session_key = b"fake-session-key"
        conn.connection = _Ws()
        # Queued during the reconnect backoff.
        conn._message_queue.put_nowait(MessageForQueue("jdev/sps/io/x/on", False))
        conn._secured_queue.append(SecuredCommand("gate", "pulse", "1234"))

        with caplog.at_level(logging.WARNING):
            task = asyncio.create_task(conn.start_listening())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except BaseException:
                pass

        assert sent and sent[0].startswith("jdev/sys/keyexchange/")
        assert "jdev/sps/io/x/on" not in sent
        assert conn._secured_queue == deque()
        assert "Dropped 1 queued command(s) and 1 secure command(s)" in caplog.text

    @pytest.mark.asyncio
    async def test_dead_socket_leftovers_are_not_sent(self, caplog):
        import logging

        conn = self._conn()
        conn.connection = None  # socket already gone
        consumer = asyncio.create_task(conn._process_message())
        await asyncio.sleep(0)
        for i in range(3):
            conn._message_queue.put_nowait(MessageForQueue(f"cmd/{i}", False))

        with caplog.at_level(logging.DEBUG):
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer

        assert conn._message_queue.empty()
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
