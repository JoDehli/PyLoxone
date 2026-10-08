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
        task = asyncio.create_task(conn.start_listening())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Connection was not replaced by start_listening.
        assert conn.connection is fake_ws


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
    async def test_drain_empty_queue(self):
        conn = self._make_conn()
        assert conn._secured_queue == deque()
        drained = await conn._drain_secured_queue()
        assert drained == 0
        assert conn._secured_queue == deque()

    @pytest.mark.asyncio
    async def test_drain_single_command(self):
        conn = self._make_conn()
        self._set_visual_hash(conn)

        conn._secured_queue.append(
            SecuredCommand("dev-uuid-1", "value", "44")
        )
        drained = await conn._drain_secured_queue()
        assert drained == 1
        assert conn._secured_queue == deque()

        # The drained command is on the message queue as a
        # MessageForQueue with flag=True.
        assert conn._message_queue.qsize() == 1
        item = conn._message_queue.get_nowait()
        assert isinstance(item, MessageForQueue)
        assert item.flag is True
        # The command text starts with ``jdev/sps/ios/{hmac}/``.
        assert item.command.startswith("jdev/sps/ios/")
        assert item.command.endswith("/dev-uuid-1/value")

    @pytest.mark.asyncio
    async def test_drain_preserves_fifo_order(self):
        conn = self._make_conn()
        self._set_visual_hash(conn)

        for i in range(5):
            conn._secured_queue.append(
                SecuredCommand(f"dev-{i}", f"v{i}", f"c{i}")
            )

        drained = await conn._drain_secured_queue()
        assert drained == 5
        assert conn._secured_queue == deque()

        # Pop the message queue and assert FIFO order.
        assert conn._message_queue.qsize() == 5
        for i in range(5):
            item = conn._message_queue.get_nowait()
            assert item.command.endswith(f"/dev-{i}/v{i}")

    @pytest.mark.asyncio
    async def test_drain_without_visual_hash_skips(self):
        """When ``_visual_hash is None``, every queued command is
        skipped (the helper returns ``None``) and the deque is
        drained. The skip is logged at DEBUG — verify the queue
        ends up empty and the message queue is empty.
        """
        conn = self._make_conn()
        assert conn._visual_hash is None

        for i in range(3):
            conn._secured_queue.append(
                SecuredCommand(f"dev-{i}", f"v{i}", f"c{i}")
            )

        drained = await conn._drain_secured_queue()
        assert drained == 0
        assert conn._secured_queue == deque()
        assert conn._message_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_drain_unknown_hash_alg_skips_individually(
        self, caplog: pytest.LogCaptureFixture
    ):
        """An unrecognised hash algorithm skips that command (logged
        at ERROR) but doesn't stop the drain — the deque ends empty
        and zero commands reach the message queue.
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
            drained = await conn._drain_secured_queue()

        assert drained == 0
        assert any(
            "Unrecognised hash algorithm" in r.message
            for r in caplog.records
        )

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