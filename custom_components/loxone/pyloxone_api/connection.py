"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import asyncio
import datetime
import hashlib
import json
import logging
import ssl
import time
import urllib
from base64 import b64decode, b64encode
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, NoReturn, Optional, Union
from urllib.parse import urlparse

import aiohttp
import websockets as wslib
import websockets.exceptions
import random
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import HMAC, SHA1, SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Util import Padding

from .const import (AES_KEY_SIZE, CMD_AUTH_WITH_TOKEN, CMD_ENABLE_UPDATES,
                    CMD_GET_API_KEY, CMD_GET_KEY, CMD_GET_KEY_AND_SALT,
                    CMD_GET_PUBLIC_KEY, CMD_GET_VISUAL_PASSWD, CMD_KEEP_ALIVE,
                    CMD_KEY_EXCHANGE, CMD_KILL_TOKEN, CMD_REFRESH_TOKEN,
                    CMD_REFRESH_TOKEN_JSON_WEB, CMD_REQUEST_TOKEN,
                    CMD_REQUEST_TOKEN_JSON_WEB, DELAY_CHECK_TOKEN_REFRESH,
                    IV_BYTES, KEEP_ALIVE_PERIOD, LLRSP_UNAUTHORISED_CODES,
                    LOXAPPPATH, MAX_RECONNECT_DELAY, MAX_REFRESH_DELAY,
                    MAX_WEBSOCKET_MESSAGE_SIZE, MESSAGE_HEADER_SIZE,
                    RECONNECT_DELAY, RECONNECT_TRIES, SALT_BYTES,
                    SALT_MAX_AGE_SECONDS, SALT_MAX_USE_COUNT,
                    SECURED_COMMAND_TIMEOUT, TIMEOUT,
                    TOKEN_PERMISSION, TOKEN_REFRESH_MAX_FAILURES,
                    WEBSOCKET_CLOSE_TIMEOUT, WEBSOCKET_READ_TIMEOUT)
from .exceptions import (LoxoneAuthEscalatedError,
                         LoxoneConnectionClosedOk, LoxoneConnectionError,
                         LoxoneException, LoxoneMaxNumOfConnectionsError,
                         LoxoneOutOfServiceException,
                         LoxoneServiceUnAvailableError, LoxoneTokenError,
                         LoxoneUnauthorisedError)
from .loxone_http_client import LoxoneAsyncHttpClient
from .loxone_token import LOXONE_EPOCH, LoxoneToken, LxJsonKeySalt
from .message import (BaseMessage, BinaryFile, Keepalive, LLResponse,
                      MessageHeader, MessageType, TextMessage,
                      check_and_decode_if_needed, parse_header, parse_message)
from .websocket_protocol import LoxoneClientConnection

_LOGGER = logging.getLogger(__name__)
import warnings

# Filter out the specific warning
warnings.filterwarnings(
    "ignore",
    message="Detected blocking call to load_verify_locations",
    module="httpx._config",
)

# Number of tracked background tasks at which :meth:`_spawn_task`
# prunes the finished ones (and reports their exceptions). Small
# enough that a dead task is reported within a few dozen messages,
# large enough that pruning stays amortised O(1) per spawn.
_TASK_PRUNE_THRESHOLD = 64

# How many messages the recv loop dispatches before it yields to the
# event loop. Every yield costs a scheduler round trip (~8 us over the
# receive pipeline), while never yielding lets a buffered stream
# accumulate unbounded pending tasks — the websocket read itself only
# yields when it waits for new network data. 64 keeps both sides
# bounded and cuts the yield overhead to a quarter of a batch of 16;
# at Miniserver update rates that is still far below the 30 s
# keepalive interval.
_DISPATCH_YIELD_BATCH = 64

# Pre-computed ``create_task`` names for the recv hot path. Building
# them inline (``f"loxone.event-{msg_type.name}"``) costs an enum
# attribute lookup plus an f-string per dispatched event; the lookup
# table turns that into one dict index.
_EVENT_TASK_NAMES: dict = {mtype: f"loxone.event-{mtype.name}" for mtype in MessageType}
_CALLBACK_TASK_NAMES: dict = {mtype: f"loxone.callback-{mtype.name}" for mtype in MessageType}

# Message types whose parsed message ``_websocket_event`` does
# anything with. Its chain only branches on TextMessage (key
# exchange, getkey, token, ...); state tables, binary files and
# keepalives fall through to ``else: pass``, so spawning a task for
# them pays the full task creation for a no-op: skipping that spawn
# measured +10.8% of receive throughput (interleaved A/B, 10 pairs,
# no overlapping runs). Keep this in sync with the ``elif`` chain in
# ``_websocket_event``: a new branch there needs its message type
# added here, or it would silently never run.
_EVENT_HANDLED_TYPES: frozenset = frozenset({MessageType.TEXT})


def time_elapsed_in_seconds():
    return int(round(time.time()))


def _format_loxone_token_expiration(
    valid_until: int | float | str,
    now: datetime.datetime | None = None,
) -> str:
    """Format a Loxone-epoch token expiry and its remaining duration."""
    expiration = LOXONE_EPOCH + datetime.timedelta(seconds=float(valid_until))
    current = now or datetime.datetime.now()
    remaining_seconds = int((expiration - current).total_seconds())
    duration = datetime.timedelta(seconds=abs(remaining_seconds))
    days = duration.days
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    direction = "in" if remaining_seconds >= 0 else "ago"
    return (
        f"{expiration:%Y-%m-%d %H:%M:%S}; {direction} "
        f"{days}d {hours}h {minutes}m {seconds}s"
    )


def percent_encode_credential(value: str) -> str:
    """Percent-encode a credential for use inside a protocol command.

    ``urllib.parse.quote(value, safe="")`` encodes every reserved
    character so the resulting string is safe to embed in a Loxone
    command path segment (e.g. ``"Ége" → "%C3%89ge"``).

    NOTE: the raw (unencoded) value is kept for *hashing* (HMAC inputs
    are not URLs), and for the HTTP basic-auth header in
    ``LoxoneAsyncHttpClient``. Only command-URL embeddings use the
    encoded form.

    VERIFY: the Miniserver is assumed to expect UTF-8 percent-encoding.
    Community knowledge points at latin-1 for some command strings; if
    a live Miniserver rejects commands containing non-ASCII credentials,
    change this single helper to ``value.encode("latin-1")`` form.
    """
    return urllib.parse.quote(value, safe="")


DEFAULT_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
}


# Websocket close codes after which reconnecting cannot succeed
# (spec "Communicating with the Miniserver": Websocket Close Codes and
# "What can go wrong?"). Retrying them forever only spams the
# Miniserver; while blocked (4003) every attempt can extend the block.
FATAL_CLOSE_CODES: dict[int, str] = {
    4003: "user is blocked after too many failed login attempts",
    4006: "user is disabled",
}


def _raise_if_fatal_close(exc: websockets.exceptions.ConnectionClosed) -> None:
    """Raise ``LoxoneUnauthorisedError`` for a close code in ``FATAL_CLOSE_CODES``.

    The ``run()`` supervisor does not retry that error; the integration
    reports the authentication failure instead of reconnecting forever.
    """
    rcvd = getattr(exc, "rcvd", None)
    code = getattr(rcvd, "code", None)
    if code in FATAL_CLOSE_CODES:
        raise LoxoneUnauthorisedError(
            f"Miniserver closed the connection: {FATAL_CLOSE_CODES[code]} "
            f"(close code {code})"
        ) from exc


# Network errors while (re)connecting: expected while the Miniserver
# reboots or is unreachable, and reported once by the caller.
# (``ConnectionError`` and ``TimeoutError`` are ``OSError`` subclasses.)
_TRANSIENT_NETWORK_ERRORS = (OSError, LoxoneConnectionError)


def _command_path_for_log(command: str) -> str:
    """Strip the arguments (tokens, hashes, values) from a command for logging.

    ``jdev/sys/killtoken/<token>/<user>`` -> ``jdev/sys/killtoken/…``,
    ``authwithtoken/<hash>/<user>`` -> ``authwithtoken/…``.
    """
    keep = 3 if command.startswith(("jdev/", "dev/")) else 1
    parts = command.split("/")
    path = "/".join(parts[:keep])
    return f"{path}/…" if len(parts) > keep else path


def parse_loxone_url(url: str) -> tuple[str, str]:
    """Parse a Loxone URL into ``(scheme, host[:port][/path])``.

    ``url`` may be in any of these forms:
      - ``http://host[:port][/path]``
      - ``https://host[:port][/path]``
      - ``host[:port][/path]`` (no scheme — defaults to ``"http"``)

    The returned host form has the scheme stripped; default ports
    (80 for ``http``/``ws``, 443 for ``https``/``wss``) are omitted,
    matching the Loxone protocol's expectation that explicit ports
    only appear when they are non-default.

    Returns ``(scheme, host)`` where ``scheme`` is ``"http"`` or
    ``"https"``.

    Raises ``ValueError`` on an unparseable host.
    """
    parsed = urlparse(url if "://" in url else f"//{url}", scheme="")
    scheme = parsed.scheme or "http"
    # Reject path-only inputs (e.g. ``/api`` — no authority component).
    if not parsed.hostname:
        raise ValueError(f"Cannot parse hostname from '{url}'")
    hostname = parsed.hostname

    if parsed.port is not None and parsed.port != DEFAULT_PORTS.get(scheme):
        host = f"{hostname}:{parsed.port}"
    else:
        host = hostname

    return scheme, host + (parsed.path or "")


def build_loxone_url(
    scheme: str, host: str, *, path: str = "/ws/rfc6455"
) -> str:
    """Build a websocket URL from ``(scheme, host)``.

    ``scheme`` may be the HTTP-style scheme (``"http"``/``"https"``)
    or the websocket-style scheme (``"ws"``/``"wss"``); the
    websocket form is derived: ``http`` → ``ws``, ``https`` → ``wss``.

    ``host`` is the bare ``host[:port][/path]`` form (no scheme),
    i.e. the second element returned by :func:`parse_loxone_url`.
    """
    if scheme in ("http", "ws"):
        ws_scheme = "ws"
    elif scheme in ("https", "wss"):
        ws_scheme = "wss"
    else:
        raise ValueError(f"Unsupported scheme '{scheme}'")
    return f"{ws_scheme}://{host}{path}"


@dataclass
class MessageForQueue:
    command: str
    flag: bool


@dataclass
class SecuredCommand:
    """A pending secure command awaiting a ``getvisusalt`` response.

    The Miniserver replies to a ``jdev/sps/getvisusalt/{user}`` call
    with a ``getvisusalt`` text message carrying the AES key + salt.
    Until that reply arrives we cannot compute the per-command HMAC,
    so we just stash the (device_uuid, value, code) tuple and let
    ``_send_next_secured_command`` build the wire command later.

    Replaces the previous design which stored **coroutines** in an
    ``asyncio.Queue(maxsize=1)`` — those were opaque, capacity-bounded
    to one item, and racy to drain.
    """

    device_uuid: str
    value: Union[str, int, float]
    code: str
    # ``time.monotonic()`` when queued; commands older than
    # ``SECURED_COMMAND_TIMEOUT`` are dropped, never sent late.
    created: float = field(default_factory=time.monotonic)


class LoxoneBaseConnection:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        token: Optional[dict] = None,
        port: int = 8080,
        timeout: Optional[float] = None,
        verify_ssl: bool = True,
        executor: Optional[Callable[..., Any]] = None,
        token_change_callback: Optional[Callable[..., Any]] = None,
    ):
        # Validate input parameters
        if not host or not isinstance(host, str):
            raise ValueError("Host must be a non-empty string")
        if not username or not isinstance(username, str):
            raise ValueError("Username must be a non-empty string")
        if not password or not isinstance(password, str):
            raise ValueError("Password must be a non-empty string")
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ValueError(f"Port must be an integer between 1 and 65535, got {port}")
        if timeout is not None and (
            not isinstance(timeout, (int, float)) or timeout < 0
        ):
            raise ValueError(
                f"Timeout must be a non-negative number or None, got {timeout}"
            )
        if not isinstance(verify_ssl, bool):
            raise ValueError("verify_ssl must be a boolean")

        self.host = host
        self.username = username
        # The username embedded in protocol commands must be
        # percent-encoded (e.g. for non-ASCII credentials). The raw value
        # is kept on ``self.username`` for hashing and HTTP basic auth.
        self._encoded_username = percent_encode_credential(username)
        self.password = password
        self.token = token
        self.port = port
        self.timeout = None if timeout == 0 else timeout
        self.verify_ssl = verify_ssl
        # Optional executor for off-loading blocking work (e.g.
        # ``json.loads`` of the multi-MB ``LoxAPP3.json``) off the
        # event loop. Shape matches ``hass.async_add_executor_job``
        # (``async def executor(target, *args)`` → awaitable).
        # ``None`` (the default) means call the function inline.
        self.executor: Optional[Callable[..., Any]] = executor
        self.connection: wslib.ClientConnection | None = None
        self._pending_task = []
        # Background tasks that should be tracked across the
        # connection's lifetime (fire-and-forget coroutines spawned
        # by the recv loop or by the keepalive / token-refresh paths).
        # ``_spawn_task`` adds to the set and registers a done
        # callback so completed tasks are removed and any
        # unhandled exception is logged at WARNING.
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self._key_update_event: Optional[asyncio.Event] = None
        self._shutdown_event = asyncio.Event()
        self._reconnect_event: asyncio.Event = asyncio.Event()
        # Set by the token handler once the first ``gettoken`` /
        # ``getjwt`` response has populated ``self._token``.
        # ``check_refresh_token`` blocks on this event instead of
        # the old 20-second sleep, so the first refresh happens
        # as soon as auth completes.
        self._authenticated_event: asyncio.Event = asyncio.Event()
        # Serialize automatic and service-triggered refreshes so
        # only one key-exchange / refresh response is in flight.
        self._token_refresh_lock = asyncio.Lock()
        self._token_refresh_event: asyncio.Event = asyncio.Event()
        self._token_refresh_error: Exception | None = None

        # Monotonic timestamp of the last inbound websocket frame.
        # Drives the receive watchdog in ``keep_alive()``: the
        # ``websockets`` library's ping/pong liveness check is
        # disabled on purpose (``_build_websocket_options``), so a
        # connection that stopped delivering frames is only noticed
        # through this marker.
        self._last_frame_time: float = time.monotonic()

        # Set when the Miniserver rejects our credentials (401 / 4003)
        # and the raising exception never left the fire-and-forget
        # event task. The recv loop and the keepalive loop re-raise it
        # so it reaches the ``run()`` supervisor.
        self._auth_failure: Optional[Exception] = None

        # ``run()``'s on_state callback, kept on the instance so
        # ``open()`` can signal "connected" without knowing about the
        # supervisor. ``None`` (the default) means no state signalling.
        self._on_state: Optional[Callable[..., Any]] = None

        # Optional callback invoked (possibly as a coroutine) when
        # the token changes. The integration passes
        # ``self._on_token_changed`` so the new token can be
        # persisted to ``ConfigEntry.data`` for the next restart.
        # The callback may be sync or async; we handle both.
        self._token_change_callback: Optional[Callable[..., Any]] = (
            token_change_callback
        )

        # Outage-tracking state for ``_note_connection_lost`` /
        # ``_note_connection_restored``. The recv loop and the
        # supervisor both call these so a single outage produces
        # exactly one WARNING ("connection lost") and one INFO
        # ("connection restored") regardless of how many
        # background tasks notice the drop.
        self._confirmed_connected: bool = False
        self._outage_active: bool = False

        # Parse the server input to extract scheme if present
        try:
            parsed = urlparse(host if "://" in host else f"//{host}", scheme="")
            self.scheme = parsed.scheme or ("https" if port == 443 else "http")
            netloc = parsed.hostname or parsed.path

            if not netloc:
                raise ValueError(f"Cannot parse hostname from '{host}'")
        except Exception as e:
            raise ValueError(f"Invalid host format '{host}': {e}") from e

        # do not use port 80 or 443 if the scheme is http/ws or https/wss
        default_port = 80 if self.scheme == "http" else 443
        used_port = port if port and port != default_port else None

        # Build the full address but without the scheme
        if used_port:
            self.url = f"{netloc}:{used_port}{parsed.path}"
        else:
            self.url = f"{netloc}{parsed.path}"

        # Generate random 16 byte AES initialisation vector (iv)
        try:
            self._iv: bytes = get_random_bytes(IV_BYTES)
            # Generate an AES256-CBC key.
            self._aes_key: bytes = get_random_bytes(AES_KEY_SIZE)
        except Exception as e:
            raise RuntimeError(f"Failed to generate cryptographic keys: {e}") from e

        self._public_key: str = ""
        self._session_key: bytes

        self.miniserver_version: list[int] = []
        self.miniserver_serial: str = ""
        self.structure_file: dict = {}
        # Set by ``open(connect_websocket=False)``: the HTTP bootstrap
        # (apiKey / LoxAPP3 / publicKey / session key) is done, but the
        # websocket is left for ``start_listening()`` to open right
        # before the key exchange. Issue #527: the Miniserver closes a
        # websocket that is not authenticated within a few seconds.
        self._websocket_deferred: bool = False

        # Validate and initialize token
        try:
            if (
                self.token
                and self.token.get("token")
                and self.token.get("valid_until")
                and self.token.get("hash_alg")
            ):
                token_str = self.token.get("token")
                valid_until = self.token.get("valid_until")
                hash_alg = self.token.get("hash_alg")
                unsecure_password = self.token.get("unsecure_password", False)

                if not isinstance(token_str, str) or not token_str:
                    raise ValueError("Token must be a non-empty string")
                if not isinstance(valid_until, (int, float)) or valid_until < 0:
                    raise ValueError("valid_until must be a non-negative number")
                if hash_alg not in ("SHA1", "SHA256"):
                    raise ValueError(
                        f"hash_alg must be 'SHA1' or 'SHA256', got '{hash_alg}'"
                    )

                self._token = LoxoneToken(
                    token=token_str,
                    valid_until=valid_until,
                    hash_alg=hash_alg,
                    key="",
                    unsecure_password=unsecure_password,
                )
            else:
                self._token = LoxoneToken()
        except Exception as e:
            _LOGGER.error(f"Failed to initialize token: {e}")
            self._token = LoxoneToken()

        self._key: str = ""
        self._user_salt: str = ""
        self._hash_alg: str = ""

        self._salt_has_expired: bool = False
        self._salt_time_stamp: int = 0
        self._salt: str = ""
        self._salt_used_count: int = 0
        # Serializes the salt decision + generation in
        # ``_send_text_command``. Several send tasks reach that point
        # concurrently (the queue consumer spawns one per message, plus
        # the direct callers in ``open()`` / token refresh), so the
        # rotation must not be decided twice or built against an
        # already-rotated ``_salt``. The lock is held only for the
        # decision, never across the AES work or the websocket send —
        # see the comment at the ``async with`` site.
        self._salt_lock: asyncio.Lock = asyncio.Lock()
        self._visual_hash = None
        # Replace synchronous Queue with asyncio.Queue with bounded size
        self._message_queue: asyncio.Queue[MessageForQueue] = asyncio.Queue(
            maxsize=1000
        )
        # FIFO of pending secure commands awaiting the Miniserver's
        # ``getvisusalt`` response. Was previously an
        # ``asyncio.Queue(maxsize=1)`` of coroutines; the new
        # ``deque`` of :class:`SecuredCommand` records is
        # capacity-unbounded (FIFO), inspectable without running,
        # and trivially drainable in O(n) by the ``getvisusalt``
        # handler.
        self._secured_queue: deque[SecuredCommand] = deque()
        self.message_header = None

    def _apply_url(self, scheme: str, url: str) -> None:
        """Update ``self.scheme`` and ``self.url`` together.

        Used when the Miniserver's Cloud-DNS redirect returns a new
        URL (e.g. ``http://192.168.1.1`` → ``https://12345.loxone.cloud``)
        so the websocket flips ``ws``→``wss`` and the HTTP client flips
        ``http``→``https`` in lockstep. ``self.url`` is the bare
        ``host[:port][/path]`` form (no scheme).
        """
        self.scheme = scheme
        self.url = url
        _LOGGER.debug("URL updated to %s://%s", scheme, url)

    def _websocket_ssl_context(self) -> ssl.SSLContext | None:
        """Return an unverified TLS context when explicitly configured."""
        if self.scheme != "https" or self.verify_ssl:
            return None

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def _build_websocket_options(self) -> dict:
        """Build the kwargs dict for ``wslib.connect(...)``.

        Centralised so the open() call site doesn't need to know
        the field names, and so tests can assert the policy in one
        place. The two non-obvious choices are:

        - ``ping_interval=None`` — the Loxone Miniserver sends its
          own 30 s TEXT keepalive, so the websockets library's
          Ping/Pong frames are redundant and would race the
          keepalive timer. Disabling them means the keepalive is
          the single liveness channel and a stalled Miniserver
          shows up in the keepalive timeout rather than a missed
          Pong.
        - ``close_timeout=WEBSOCKET_CLOSE_TIMEOUT`` — when the
          integration calls ``close()`` it gives the Miniserver
          up to 10 s to acknowledge the close frame before the
          websockets library drops the TCP connection.

        ``open_timeout`` and ``max_size`` keep their previous
        values. ``compression`` is explicitly disabled because
        the Loxone binary protocol and the legacy
        per-message-deflate are a known-bad combination — the
        websocket frames contain binary headers and JSON payloads
        where per-message-deflate can break frame boundaries.
        """
        return {
            "open_timeout": self.timeout or TIMEOUT,
            "create_connection": LoxoneClientConnection,
            "compression": None,
            "max_size": MAX_WEBSOCKET_MESSAGE_SIZE,
            "ping_interval": None,
            "close_timeout": WEBSOCKET_CLOSE_TIMEOUT,
        }

    @property
    def is_connected(self) -> bool:
        """Check if the websocket connection is open."""
        return (
            self.connection is not None
            and hasattr(self.connection, "protocol")
            and self.connection.protocol.state.name == "OPEN"
        )

    def get_token_dict(self) -> dict:
        try:
            return {
                "token": self._token.token,
                "valid_until": self._token.valid_until,
                "hash_alg": self._token.hash_alg,
                "unsecure_password": self._token.unsecure_password,
            }
        except AttributeError as e:
            _LOGGER.error(f"Token attributes missing: {e}")
            return {}

    def reset_token(self):
        try:
            self._token = LoxoneToken()
            _LOGGER.debug("Token reset successfully")
        except Exception as e:
            _LOGGER.error(f"Failed to reset token: {e}")

    async def _send_text_command(
        self, command: str = "", encrypted: bool = False
    ) -> TextMessage:
        """Send a (text) command to the Miniserver, and return the response.

        If encrypted=True, the message will be encrypted, and will be sent using
        Loxone's 'jdev/sys/enc' command. We do not handle 'jdev/sys/fenc'
        full encryption, which encrypts the response as well.

        Miniserver gen 2 uses TLS, so most commands do not need encrypting. But
        some commands (to do with tokens) still seem to need it.

        Crypto choices
        --------------

        For ``encrypted=True`` commands the plaintext is encrypted
        with **AES-256-CBC** (``Crypto.Cipher.AES``) under two
        per-installation keys generated in ``__init__``:

          - ``self._aes_key``  — 32 random bytes (AES-256).
          - ``self._iv``       — 16 random bytes (CBC IV).

        Both are generated via ``Crypto.Random.get_random_bytes``.
        **The IV is fixed for the lifetime of the connection** —
        it is not re-derived per-message. Loxone's ``jdev/sys/enc``
        protocol expects this fixed-IV behaviour; if a future
        Loxone firmware release requires a per-message IV, this
        is the single place to change.

        Plaintext is PKCS#7-padded to 16 bytes (``Padding.pad``)
        before encryption. The wire form is the base64-encoded
        ciphertext URL-percent-encoded into the
        ``jdev/sys/enc/{b64}`` command path.

        Salt rotation
        -------------

        ``self._salt`` (a 16-byte hex string) is the **server-side
        pre-shared salt** sent to the Miniserver with every
        encrypted command so the Miniserver can derive the same
        session key. ``_new_salt_needed()`` decides when to
        rotate:

          - ``SALT_MAX_USE_COUNT`` — rotate after this many uses
            of the current salt.
          - ``SALT_MAX_AGE_SECONDS`` — rotate after this many
            seconds since ``_generate_salt`` last ran.

        When a rotation is due, the new salt is sent to the
        Miniserver via a ``nextSalt/{old}/{new}/{command}``
        command (the old salt is included so the Miniserver can
        validate the rotation). The trailing NUL byte
        (``\\x00``) after ``{command}`` is undocumented but
        required by the Miniserver's command parser.

        The decision and the generation run under
        ``self._salt_lock`` (see ``__init__``) because the send
        path is concurrent: the queue consumer spawns one task per
        message and ``open()`` / token refresh call this method
        directly. The lock is released before the AES work and the
        websocket send, so it never covers I/O.

        Hash algorithm fallback
        -----------------------

        Both token-auth HMACs (``_hash_token`` /
        ``_hash_credentials``) and secured-command HMACs
        (``_secured_command_text``) branch on
        ``hash_alg in {"SHA1", "SHA256"}``. SHA1 is the
        historical default; the Loxone ``hashAlg`` field in the
        key/salt response selects. Unknown algorithms log at
        ERROR and abort the operation — the connection layer
        does not silently fall back to a weaker hash.

        Secured commands additionally depend on the
        ``self._visual_hash`` field populated by the
        ``getvisusalt`` handler (see :class:`SecuredCommand`
        for the queue plumbing).

        """
        # Lazy %-args: this runs for every outgoing command, so the command
        # string must not be built unless DEBUG is enabled (G004 bans the
        # f-string variant).
        if encrypted:
            # Encrypted commands carry secrets (raw token for killtoken,
            # credential / token hashes, secured-command HMACs): log only
            # the command path, never the plaintext.
            _LOGGER.debug(
                "Send encrypted command: %s", _command_path_for_log(command)
            )
        else:
            _LOGGER.debug("Send text command: %s", command)
        # Issue #514: during a normal token expiry the Miniserver closes the
        # websocket (1000) and sends fail until the supervisor reconnects.
        # Raising ``LoxoneConnectionClosedOk`` here lets the supervisor's
        # DEBUG-level handler run the normal reconnect path instead of
        # spamming ERROR logs at every command attempt.
        #
        # Checked *before* the salt decision on purpose: rotating for a
        # command that provably cannot be sent would advance the local salt
        # past the Miniserver's for nothing. (A reconnect recovers anyway —
        # ``open()`` calls ``_generate_salt()`` — but there is no reason to
        # desync while the socket is still up, nor to pay for the AES work.)
        if not self.connection or not self.is_connected:
            raise LoxoneConnectionClosedOk("Cannot send command - connection is not open")
        # Snapshot the reference: ``close()`` runs in another task and nulls
        # ``self.connection``, which is now further away because the salt
        # decision and the AES work happen in between.
        connection = self.connection
        if encrypted:
            # Salt state (``_salt`` / ``_salt_used_count``) is shared
            # across every concurrent send task, so decide + generate
            # atomically. Without the lock a second sender could decide
            # while a rotation is in flight and build its command with
            # a salt the Miniserver has not (or already) switched to.
            # Only the decision lives inside the lock: the AES work and
            # the websocket send below stay outside, so the critical
            # section never waits on I/O and the send pipeline keeps
            # its fire-and-forget throughput.
            async with self._salt_lock:
                if self._new_salt_needed():
                    old_salt = self._salt
                    self._generate_salt()
                    # The miniserver needs the text terminated with a zero byte,
                    # though this is not documented
                    command_string = f"nextSalt/{old_salt}/{self._salt}/{command}\x00"
                else:
                    command_string = f"salt/{self._salt}/{command}\x00"
            padded_bytes = Padding.pad(bytes(command_string, "utf-8"), 16)
            aes_cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
            cipher = b64encode(aes_cipher.encrypt(padded_bytes))
            enc_cipher = urllib.parse.quote(cipher.decode())
            command = f"jdev/sys/enc/{enc_cipher}"
        try:
            # Send a plain str (not a list): websockets fragments the
            # payload when given a list, which the Loxone protocol does
            # not expect.
            await connection.send(command)
        except websockets.ConnectionClosedOK:
            raise LoxoneConnectionClosedOk(
                "Connection closed normally while sending command"
            )
        except Exception as e:
            _LOGGER.debug("Error while sending: %s", e)
            raise

    def _decrypt(self, command: str) -> bytes:
        """AES decrypt a command returned by the miniserver."""
        # control will be in the form:
        # "jdev/sys/enc/CHG6k...A=="
        # Encrypted strings returned by the miniserver are not %encoded (even
        # if they were when sent to the miniserver )
        remove_text = "jdev/sys/enc/"
        enc_text = (
            command[len(remove_text) :] if command.startswith(remove_text) else command
        )
        decoded = b64decode(enc_text)
        aes_cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        decrypted = aes_cipher.decrypt(decoded)
        unpadded = Padding.unpad(decrypted, 16)
        # The miniserver seems to terminate the text with a zero byte
        return unpadded.rstrip(b"\x00")

    def _generate_salt(self) -> None:
        try:
            _LOGGER.debug("Generating a new salt")
            self._salt = get_random_bytes(SALT_BYTES).hex()
            self._salt_time_stamp = time_elapsed_in_seconds()
            self._salt_used_count = 0
        except Exception as e:
            _LOGGER.error(f"Failed to generate salt: {e}")
            raise RuntimeError(f"Salt generation failed: {e}") from e

    def _new_salt_needed(self):
        try:
            self._salt_used_count += 1
            if (
                self._salt_used_count > SALT_MAX_USE_COUNT
                or time_elapsed_in_seconds() - self._salt_time_stamp
                > SALT_MAX_AGE_SECONDS
            ):
                return True
            return False
        except Exception as e:
            _LOGGER.error(f"Error checking salt expiration: {e}")
            return True  # Generate new salt on error to be safe

    async def _refresh_token(self):
        try:
            token_hash = self._hash_token()
            if token_hash is None:
                raise RuntimeError("Failed to hash token")

            if self.miniserver_version < [10, 2]:
                command = f"{CMD_REFRESH_TOKEN}{token_hash}/{self._encoded_username}"
            else:
                command = f"{CMD_REFRESH_TOKEN_JSON_WEB}{token_hash}/{self._encoded_username}"

            try:
                await self._message_queue.put(MessageForQueue(command, True))
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout adding refresh token command to queue")
                raise
        except Exception as e:
            _LOGGER.error(f"Token refresh failed: {e}")
            raise

    async def async_refresh_token(self, timeout: float = 30.0) -> dict:
        """Force an immediate token refresh and await Miniserver confirmation.

        This is shared by the automatic refresh loop and the HA service.
        The operation first obtains a fresh session key, sends the
        version-appropriate refresh command, then waits for the refresh
        response handler to update the token. A lock prevents overlapping
        automatic/manual requests on the same websocket.
        """
        if not self._authenticated_event.is_set() or not self._token.token:
            raise LoxoneTokenError("Cannot refresh before authentication")
        if self._shutdown_event.is_set() or not self.is_connected:
            raise LoxoneConnectionClosedOk(
                "Cannot refresh token while disconnected"
            )

        async with self._token_refresh_lock:
            if self._shutdown_event.is_set() or not self.is_connected:
                raise LoxoneConnectionClosedOk(
                    "Connection closed before token refresh started"
                )

            old_key = self._key
            key_updated_event = asyncio.Event()
            self._key_update_event = key_updated_event
            self._token_refresh_event.clear()
            self._token_refresh_error = None

            try:
                self._spawn_task(
                    self._send_text_command(CMD_GET_KEY, encrypted=False),
                    name="loxone.send-keyexchange",
                )
                await asyncio.sleep(0)
                await asyncio.wait_for(key_updated_event.wait(), timeout=15.0)
                if self._key == old_key:
                    raise LoxoneTokenError(
                        "Miniserver did not provide a new session key"
                    )

                await self._refresh_token()
                await asyncio.wait_for(
                    self._token_refresh_event.wait(), timeout=timeout
                )
                if self._token_refresh_error is not None:
                    raise self._token_refresh_error
                return self.get_token_dict()
            finally:
                if self._key_update_event is key_updated_event:
                    self._key_update_event = None

    def _signal_token_changed(self) -> None:
        """Notify the integration that the token has changed.

        The integration passes a ``token_change_callback`` that
        merges the new token into ``ConfigEntry.data`` so a HA
        restart can pick it up. The callback may be sync or async;
        we await it if it's a coroutine.

        The token dict is built from ``self.get_token_dict()`` so
        the contract with the integration is stable.

        Failures are logged at WARNING, never raised — a
        persistence error must not break the websocket path.
        """
        if self._token_change_callback is None:
            return
        try:
            token_dict = self.get_token_dict()
            result = self._token_change_callback(token_dict)
            if asyncio.iscoroutine(result):
                # Run the async callback in a tracked task so
                # any exception is logged at WARNING (not
                # silently dropped) and we don't block the
                # caller (the recv loop or the token handler).
                self._spawn_task(
                    self._await_callback(result),
                    name="loxone.token-changed",
                )
        except Exception as e:
            _LOGGER.warning(
                "token_change_callback raised: %s", e, exc_info=True
            )

    async def _await_callback(self, coro) -> None:
        """Await a coroutine returned by ``_token_change_callback``.

        Extracted so ``_signal_token_changed`` can hand the
        coroutine to ``_spawn_task`` cleanly. Exceptions are
        logged via the standard done-callback path; this
        wrapper just drains the coroutine.
        """
        await coro

    async def kill_token(self) -> None:
        """Invalidate the current token on the Miniserver.

        Sends ``jdev/sys/killtoken/<token>/<user>``. Both path
        segments are required — without the user segment the
        Miniserver answers ``400`` and keeps the token usable
        (checked against a live Miniserver, JWT-era firmware).
        The token is sent raw: this firmware wants the JWT
        itself here, a getkey-hashed token is refused with
        ``401``. Because it is raw, the command goes through
        command encryption (``jdev/sys/enc/``) like the other
        token commands — sent plain, the token would cross the
        network in clear text on an unencrypted ``ws://``
        connection (Gen1 Miniserver).

        The Miniserver drops the session as part of the kill, so
        no reply frame comes back and a subsequent HA restart
        requires a fresh username/password auth instead of
        reusing the killed token. We log and swallow errors so
        ``async_cleanup`` can still run ``close()`` after.
        """
        if not self._token or not self._token.token:
            _LOGGER.debug(
                "kill_token: no token to invalidate; nothing to do"
            )
            return
        try:
            token = self._token.token
            command = f"{CMD_KILL_TOKEN}/{token}/{self._encoded_username}"
            # Never log the token itself.
            _LOGGER.debug("kill_token: sending killtoken for %s", self.username)
            # Fire the kill on the wire. No reply frame comes
            # back: the Miniserver drops the session as part of
            # the kill, and ``close()`` follows straight away in
            # ``async_cleanup`` anyway. The ``try/except`` guards
            # against a closed-websocket race during teardown.
            await self._send_text_command(command, encrypted=True)
        except Exception as e:
            _LOGGER.warning("kill_token: failed to send: %s", e)

    def _hash_token(self):
        try:
            if not self._token or not self._token.token:
                _LOGGER.error("No token available to hash")
                return None

            if not self._key:
                _LOGGER.error("No key available for token hashing")
                return None

            token_hash_str = f"{self._token.token}"

            if self._hash_alg == "SHA1":
                hash_module = SHA1
            elif self._hash_alg == "SHA256":
                hash_module = SHA256
            else:
                _LOGGER.error(f"Unrecognised hash algorithm: {self._hash_alg}")
                return None

            try:
                key_bytes = bytes.fromhex(self._key)
            except ValueError as e:
                _LOGGER.error(f"Invalid hex key format: {e}")
                return None

            try:
                digester = HMAC.new(
                    key_bytes, token_hash_str.encode("utf-8"), hash_module
                )
                return digester.hexdigest()
            except Exception as e:
                _LOGGER.error(f"HMAC generation failed: {e}")
                return None

        except Exception as e:
            _LOGGER.error(f"Token hashing error: {e}")
            return None

    def _secured_command_text(
        self,
        device_uuid: str,
        value: Union[str, int, float],
        code: str,
    ) -> Optional[str]:
        """Build the wire command text for a pending secure command.

        Pure function (no IO). Returns ``None`` if
        :attr:`_visual_hash` has not been populated yet (the
        :class:`getvisusalt` response has not arrived);
        ``_send_next_secured_command`` then sends nothing.

        Also returns ``None`` for an unrecognised hash algorithm.
        """
        if self._visual_hash is None:
            _LOGGER.debug(
                "Secured command for %s skipped: visual hash not yet "
                "populated (waiting for getvisusalt response)",
                device_uuid,
            )
            return None

        pwd_hash_str = code + ":" + self._visual_hash.salt
        if self._visual_hash.hash_alg == "SHA1":
            m = hashlib.sha1()
            hash_module = SHA1
        elif self._visual_hash.hash_alg == "SHA256":
            m = hashlib.sha256()
            hash_module = SHA256
        else:
            _LOGGER.error(
                "Unrecognised hash algorithm: {}".format(self._visual_hash.hash_alg)
            )
            return None

        m.update(pwd_hash_str.encode("utf-8"))
        pwd_hash = m.hexdigest().upper()
        digester = HMAC.new(
            bytes.fromhex(self._visual_hash.key),
            pwd_hash.encode("utf-8"),
            hash_module,
        )
        new_hash = digester.hexdigest()
        return f"jdev/sps/ios/{new_hash}/{device_uuid}/{value}"

    def _pop_secured_command(self) -> Optional[SecuredCommand]:
        """Pop the oldest pending secure command that has not expired.

        Expired commands (older than ``SECURED_COMMAND_TIMEOUT``) are
        dropped with a warning: their ``getvisusalt`` reply was lost
        or failed, and sending them now would execute a secured
        action long after the user asked for it.
        """
        now = time.monotonic()
        while self._secured_queue:
            cmd = self._secured_queue.popleft()
            if now - cmd.created <= SECURED_COMMAND_TIMEOUT:
                return cmd
            _LOGGER.warning(
                "Secure command for %s dropped: no visual salt within %s s",
                cmd.device_uuid,
                SECURED_COMMAND_TIMEOUT,
            )
        return None

    async def _send_next_secured_command(self) -> bool:
        """Send the secure command that a ``getvisusalt`` reply belongs to.

        Every ``send_secured_websocket_command`` sends exactly one
        ``getvisusalt`` request, and the Miniserver answers them in
        order, so each reply releases exactly one command (FIFO).
        Draining the whole queue on one reply used to send commands
        whose own request had failed together with the next one.

        Returns True if a command was queued for sending.
        """
        cmd = self._pop_secured_command()
        if cmd is None:
            return False
        try:
            command_text = self._secured_command_text(
                cmd.device_uuid, cmd.value, cmd.code
            )
        except Exception as e:
            _LOGGER.error(
                f"Error building secured command text for "
                f"{cmd.device_uuid}: {e}"
            )
            return False
        if command_text is None:
            return False
        await self._message_queue.put(MessageForQueue(command_text, True))
        return True

    def _drop_next_secured_command(self, reason: str) -> None:
        """Discard the secure command a failed ``getvisusalt`` belongs to."""
        cmd = self._pop_secured_command()
        if cmd is not None:
            _LOGGER.warning(
                "Secure command for %s not sent: %s", cmd.device_uuid, reason
            )

    async def _send_secure(self, device_uuid, value, code):
        """Send a single pre-built secure command to the Miniserver.

        Retained for callers that have already obtained a visual
        hash and want to skip the queue path. The
        ``send_secured_websocket_command`` callers go through
        ``_secured_queue`` + ``_secured_command_text`` instead.
        """
        command_text = self._secured_command_text(device_uuid, value, code)
        if command_text is None:
            # Nothing to send — either no visual hash or unknown
            # algorithm. Logged inside the helper.
            return None
        try:
            await self._message_queue.put(MessageForQueue(command_text, True))
        except asyncio.TimeoutError:
            _LOGGER.error(f"Timeout queueing secure command for {device_uuid}")
            raise
        return None

    def _hash_credentials(self):
        try:
            pwd_hash_str = f"{self.password}:{self._user_salt}"
            if self._hash_alg == "SHA1":
                m = hashlib.sha1()
                hash_module = SHA1

            elif self._hash_alg == "SHA256":
                m = hashlib.sha256()
                hash_module = SHA256
            else:
                _LOGGER.error(f"Unrecognised hash algorithm: {self._hash_alg}")
                return None

            m.update(pwd_hash_str.encode("utf-8"))
            pwd_hash = m.hexdigest().upper()
            pwd_hash = f"{self.username}:{pwd_hash}"
            digester = HMAC.new(
                bytes.fromhex(self._key), pwd_hash.encode("utf-8"), hash_module
            )
            _LOGGER.debug("hash_credentials successfully...")
            return digester.hexdigest()
        except ValueError:
            _LOGGER.debug("error hash_credentials...")
            return None


class LoxoneConnection(LoxoneBaseConnection):
    connection: Optional[LoxoneClientConnection]
    _recv_loop: Optional["asyncio.Task[None]"]

    # Errors the :meth:`run` supervisor treats as recoverable
    # and retries with exponential backoff. Anything else
    # propagates to the caller.
    #
    # Deliberately explicit (no blanket ``LoxoneException`` entry):
    # a token error stays in here because it is the expected first
    # leg of the token-expiry self-heal — a reconnect re-authenticates
    # with the password. Auth *escalations*
    # (:class:`LoxoneAuthEscalatedError`) and credential rejections
    # (:class:`LoxoneUnauthorisedError`) are handled in dedicated
    # ``except`` clauses of :meth:`run` and must NOT be retried.
    RETRYABLE_SESSION_ERRORS = (
        LoxoneConnectionClosedOk,
        LoxoneConnectionError,
        LoxoneTokenError,
        LoxoneOutOfServiceException,
        LoxoneServiceUnAvailableError,
        LoxoneMaxNumOfConnectionsError,
        OSError,
        TimeoutError,
        websockets.exceptions.ConnectionClosed,
    )

    async def __aenter__(self) -> "LoxoneConnection":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def start_listening(
        self, callback: Optional[Callable[[str, Any], Optional[Awaitable[None]]]] = None
    ) -> None:
        """Open, and start listening."""

        if self.connection is None and self._websocket_deferred:
            # Bootstrap already done by ``open(connect_websocket=False)``;
            # only the websocket is missing. Connecting it here, directly
            # before the key exchange below, keeps the unauthenticated
            # window short (issue #527).
            _LOGGER.debug("Opening the deferred websocket connection.")
            await self._connect_websocket()
        elif self.connection is None:
            _LOGGER.debug("No existing connection found. Opening a new connection.")
            await self.open()
        else:
            _LOGGER.debug("Using existing connection.")

        # The shutdown event is not cleared here: ``close()`` may have
        # been called while ``open()`` was still bootstrapping (that can
        # take minutes of HTTP retries). Clearing it revived a closed
        # connection; instead close the socket that was opened anyway.
        if self._shutdown_event.is_set():
            _LOGGER.debug("Shutdown requested while connecting; not listening")
            connection, self.connection = self.connection, None
            if connection is not None:
                await connection.close()
            return

        # Commands queued before this session (e.g. during the
        # reconnect backoff) would reach the Miniserver right after the
        # key exchange, before the login, and be rejected with 400.
        self._discard_queued_messages(
            "queued while disconnected", level=logging.WARNING
        )

        async def keep_alive() -> None:
            """Send keep-alive messages to the Miniserver."""
            # Issue #514: a normal token expiry / websocket closure (1000)
            # is the expected end-state of this loop, not an error. Log at
            # DEBUG and return cleanly so HA's task observer does not log
            # the task as having raised. The supervisor (``start_listening``
            # / the recv loop) detects the dead connection through the
            # recv-side ``async for`` and triggers the reconnect.
            try:
                while True:
                    await asyncio.sleep(KEEP_ALIVE_PERIOD)
                    # Receive watchdog: the Miniserver sends a
                    # KEEPALIVE frame about every KEEP_ALIVE_PERIOD
                    # seconds, so a connection that delivered no frame
                    # at all for WEBSOCKET_READ_TIMEOUT is stale — a
                    # half-open socket (roaming, pulled cable, frozen
                    # Miniserver) still accepts our keepalive writes
                    # for minutes, and the ``websockets`` ping/pong
                    # check that used to catch this is disabled (see
                    # ``_build_websocket_options``). Raise so the
                    # supervisor tears the connection down and
                    # reconnects; ``self.close()`` is deliberately NOT
                    # called from here — it would await ourselves via
                    # ``self._pending_task``.
                    silence = time.monotonic() - self._last_frame_time
                    if silence > WEBSOCKET_READ_TIMEOUT:
                        reason = (
                            f"no inbound frame for {int(silence)}s "
                            f"(limit {WEBSOCKET_READ_TIMEOUT}s)"
                        )
                        self._note_connection_lost(reason)
                        raise LoxoneConnectionError(reason)
                    # A hard auth rejection (401/4003) recorded on the
                    # fire-and-forget event task is escalated here as
                    # well — the Miniserver answers a rejected token
                    # with silence, so without this check we would wait
                    # for the watchdog above.
                    if self._auth_failure is not None:
                        reason = f"auth rejected: {self._auth_failure}"
                        self._note_connection_lost(reason)
                        raise self._auth_failure
                    try:
                        # Direct ``await`` — no point wrapping a
                        # single coroutine in ``create_task`` and
                        # then awaiting the resulting task. Keeps
                        # the exception flow obvious.
                        await self._send_text_command(
                            CMD_KEEP_ALIVE, encrypted=False
                        )
                    except LoxoneConnectionClosedOk:
                        self._note_connection_lost(
                            "keep-alive detected closed websocket"
                        )
                        return
                    except Exception as exc:
                        _LOGGER.warning("Keep-alive message failed: %s", exc)
                        raise
            except asyncio.CancelledError:
                _LOGGER.debug("Keep-alive task cancelled")
                raise
            except Exception as exc:
                _LOGGER.warning("Keep-alive task encountered an error: %s", exc)
                raise

        async def check_refresh_token() -> NoReturn:
            """Check if the token needs to be refreshed.

            Waits on ``self._authenticated_event`` for the first
            ``gettoken`` / ``getjwt`` response, then enters the
            50%-of-lifetime refresh cycle. The previous
            implementation slept 20 s (DELAY_CHECK_TOKEN_REFRESH)
            and clamped ``seconds_to_refresh`` to 1 s as a
            fallback if the token wasn't ready yet — both hacks
            are gone now that the event is the synchronisation
            point.

            A consecutive-failure counter escalates to
            ``LoxoneTokenError`` after
            ``TOKEN_REFRESH_MAX_FAILURES`` cycles; the supervisor
            propagates that as a hard auth failure.
            """
            _LOGGER.debug(f"Start check refresh token task...")
            # Block on the first token. Cancelled cleanly on
            # shutdown.
            await self._authenticated_event.wait()
            consecutive_failures = 0
            try:
                while not self._shutdown_event.is_set():
                    try:
                        # Calculate 50% of the token lifetime as an integer and limit it to MAX_REFRESH_DELAY
                        candidate = int(self._token.seconds_to_expire() * 0.5)

                        def generate_refresh_time_log(_seconds_to_refresh: int) -> str:
                            days, remainder = divmod(_seconds_to_refresh, 86400)
                            hours, seconds = divmod(remainder, 3600)
                            minutes, seconds = divmod(seconds, 60)
                            return f"{days}d {hours}h {minutes}m {seconds}s"

                        seconds_to_refresh = max(1, min(candidate, MAX_REFRESH_DELAY))
                        # Log the *next refresh deadline*, not the token
                        # validity: "Seconds to refresh token: 5h" is easily
                        # misread as "token valid for 5h". Both numbers are
                        # printed so the relation is obvious.
                        _LOGGER.debug(
                            "Next token refresh in %s (token valid until %s; %s)",
                            generate_refresh_time_log(seconds_to_refresh),
                            self._token.valid_until,
                            _format_loxone_token_expiration(
                                self._token.valid_until
                            ),
                        )

                        scheduled_valid_until = self._token.valid_until
                        await asyncio.sleep(seconds_to_refresh)
                        # Check shutdown before proceeding
                        if self._shutdown_event.is_set():
                            break
                        # A manual refresh may have completed while
                        # this automatic timer was sleeping. Recompute
                        # from the new token instead of immediately
                        # refreshing it a second time.
                        if self._token.valid_until != scheduled_valid_until:
                            continue

                        try:
                            await self.async_refresh_token()
                            consecutive_failures = 0
                        except asyncio.CancelledError:
                            raise
                        except LoxoneUnauthorisedError:
                            raise
                        except Exception as exc:
                            _LOGGER.warning(
                                "Error in token refresh cycle: %s", exc
                            )
                            consecutive_failures += 1
                            await self._maybe_escalate_auth(
                                consecutive_failures
                            )
                            await asyncio.sleep(1)

                    except asyncio.CancelledError:
                        raise
                    except (
                        LoxoneTokenError,
                        LoxoneAuthEscalatedError,
                        LoxoneUnauthorisedError,
                    ):
                        # Token errors stay retryable for the
                        # supervisor (token-expiry self-heal); an
                        # escalation from ``_maybe_escalate_auth``
                        # and a 401 on the refresh itself must
                        # propagate unchanged — the catch-all below
                        # would count the 401 as an ordinary failure
                        # and keep refreshing with a rejected token.
                        raise
                    except Exception as e:
                        # Issue #514: transient cycle errors during the
                        # token-expiry self-heal. Demote to WARNING; we
                        # sleep 1 s and retry.
                        _LOGGER.warning("Error in token refresh cycle: %s", e)
                        consecutive_failures += 1
                        await self._maybe_escalate_auth(
                            consecutive_failures
                        )
                        await asyncio.sleep(1)  # Avoid tight loop on errors

            except asyncio.CancelledError:
                _LOGGER.debug("Token refresh task cancelled")
                raise
            except LoxoneTokenError:
                _LOGGER.warning("Token refresh task escalating to supervisor")
                raise
            except LoxoneAuthEscalatedError:
                _LOGGER.warning(
                    "Token refresh task escalating to supervisor "
                    "(refresh failed repeatedly)"
                )
                raise
            except LoxoneUnauthorisedError:
                _LOGGER.warning(
                    "Token refresh rejected by the Miniserver (unauthorised)"
                )
                raise
            except Exception as exc:
                # Issue #514: see above. Demote to WARNING.
                _LOGGER.warning("Token refresh task failed: %s", exc)
                raise

        try:
            if not self._session_key:
                raise RuntimeError("Session key not initialized")

            await self.connection.send(
                f"{CMD_KEY_EXCHANGE}{self._session_key.decode()}"
            )
        except websockets.exceptions.ConnectionClosed as e:
            # A blocked user (4003) is closed right after the socket
            # opens, so this send is where it shows up first.
            _raise_if_fatal_close(e)
            _LOGGER.error(f"Failed to send key exchange: {e}")
            raise
        except Exception as e:
            _LOGGER.error(f"Failed to send key exchange: {e}")
            raise

        async def reconnect_task() -> None:
            try:
                while True:
                    # Create explicit tasks for the event waits (coroutines are not allowed)
                    t_shutdown = asyncio.create_task(self._shutdown_event.wait())
                    t_reconnect = asyncio.create_task(self._reconnect_event.wait())

                    try:
                        _done, _pending = await asyncio.wait(
                            {t_shutdown, t_reconnect},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    finally:
                        # Ensure any still-pending tasks are canceled to avoid leaks
                        for p in (t_shutdown, t_reconnect):
                            if not p.done():
                                p.cancel()

                    # Shutdown requested -> exit cleanly
                    if self._shutdown_event.is_set():
                        return

                    # Reconnect requested -> clear event and raise to break listening
                    if self._reconnect_event.is_set():
                        self._reconnect_event.clear()
                        raise LoxoneTokenError(
                            "token rejected; reconnecting to re-authenticate"
                        )
            except asyncio.CancelledError:
                # Task was canceled during shutdown
                raise

        # noinspection PyUnreachableCode
        self._pending_task = [
            asyncio.create_task(self._do_start_listening(callback, self.connection)),
            asyncio.create_task(self._process_message()),
            asyncio.create_task(keep_alive()),
            asyncio.create_task(check_refresh_token()),
            asyncio.create_task(reconnect_task()),
        ]

        try:
            done, pending = await asyncio.wait(
                self._pending_task, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                try:
                    await task
                except websockets.exceptions.ConnectionClosedOK:
                    self._note_connection_lost(
                        "websocket closed cleanly (close code 1000)"
                    )
                    raise LoxoneConnectionClosedOk
                except LoxoneTokenError as e:
                    # Expected control flow: the token-expiry self-heal
                    # (authwithtoken 401, logged at DEBUG) or the refresh
                    # loop's escalation (logged at WARNING where it is
                    # raised). ``run()`` reconnects; no ERROR here.
                    _LOGGER.debug("Token error: %s", e)
                    raise
                except LoxoneOutOfServiceException as e:
                    _LOGGER.error(f"Miniserver out of service: {e}")
                    raise
                except websockets.exceptions.ConnectionClosedError as e:
                    # 4003 / 4006 (blocked / user disabled) are final;
                    # see ``_raise_if_fatal_close``.
                    _raise_if_fatal_close(e)
                    # Issue #514: an abnormal websocket close is the trigger
                    # for the reconnect-and-self-heal path, not a hard
                    # failure. Log at WARNING and surface as
                    # LoxoneConnectionError so the supervisor reloads.
                    self._note_connection_lost(
                        f"websocket closed with error: {e}"
                    )
                    raise LoxoneConnectionError
                except websockets.exceptions.ConnectionClosed as e:
                    _raise_if_fatal_close(e)
                    self._note_connection_lost(
                        f"websocket closed: {e}"
                    )
                    raise LoxoneConnectionError("Connection closed") from None
                except asyncio.CancelledError:
                    pass
                    # Don't raise, this is expected during shutdown
                except LoxoneConnectionClosedOk:
                    # Deliberate control flow, not a task failure.
                    raise
                except (LoxoneUnauthorisedError, LoxoneAuthEscalatedError) as e:
                    # Credential rejection / refresh escalation: the
                    # ``run()`` supervisor propagates this to the
                    # integration, which clears the token and reloads.
                    # Do not log it as an ERROR with traceback — the
                    # WARNING above (``_check_auth_response`` /
                    # ``_maybe_escalate_auth``) is the user-facing message.
                    _LOGGER.warning(
                        "Loxone authentication failed, not retrying: %s", e
                    )
                    raise
                except LoxoneConnectionError as e:
                    # Expected control flow (recv loop noticed a closed
                    # socket, or the keepalive watchdog declared the
                    # connection stale): the supervisor reconnects with
                    # backoff, so a traceback would only be noise.
                    _LOGGER.warning("Loxone connection error: %s", e)
                    raise
                except Exception as e:
                    _LOGGER.error(
                        f"Task {task} raised an exception: {e}", exc_info=True
                    )
                    raise
        except asyncio.CancelledError:
            _LOGGER.debug("Listening task cancelled")
            raise
        except (LoxoneConnectionError, LoxoneTokenError, LoxoneConnectionClosedOk):
            raise
        except Exception:
            raise
        finally:
            # Cancel pending tasks
            for task in self._pending_task:
                if task and not task.done():
                    task.cancel()

            if self._pending_task:
                await asyncio.gather(*self._pending_task, return_exceptions=True)

    async def _maybe_escalate_auth(self, consecutive_failures: int) -> None:
        """Raise after enough consecutive refresh failures.

        Called by the refresh loop on each failed cycle. The
        counter is reset by the caller on a successful refresh.
        After ``TOKEN_REFRESH_MAX_FAILURES`` consecutive failures we
        raise :class:`LoxoneAuthEscalatedError`; the supervisor
        treats that as a hard auth failure and stops retrying —
        the integration clears the token and reloads instead of
        refreshing forever.

        It is intentionally *not* a :class:`LoxoneTokenError`: that
        one stays retryable (token-expiry self-heal), while this one
        has to be escalated.
        """
        if consecutive_failures >= TOKEN_REFRESH_MAX_FAILURES:
            _LOGGER.warning(
                "Token refresh failed %d times in a row; "
                "escalating to LoxoneAuthEscalatedError",
                consecutive_failures,
            )
            raise LoxoneAuthEscalatedError(
                f"Token refresh failed {consecutive_failures} times"
            )

    def _note_connection_lost(self, reason: str) -> None:
        """Mark the connection as lost and log a single WARNING.

        Called from the recv loop, the keepalive task, and the
        supervisor whenever they detect the connection has
        dropped. The ``_outage_active`` flag makes sure a
        single outage produces exactly one WARNING even if
        multiple tasks notice the drop in quick succession.
        Subsequent calls before ``_note_connection_restored``
        are logged at DEBUG ("already flagged").
        """
        if self._outage_active:
            _LOGGER.debug(
                "Connection lost (already flagged): %s", reason
            )
            return
        self._outage_active = True
        _LOGGER.warning("Connection lost: %s", reason)

    def _note_connection_restored(self) -> None:
        """Mark the connection as restored and log a single INFO.

        Called from the recv loop / supervisor once a fresh
        ``open()`` cycle has succeeded. Clears the
        ``_outage_active`` flag so the next drop will produce
        another WARNING. The ``_confirmed_connected`` flag
        distinguishes "we just reconnected after a known
        outage" (announce it) from "we just initialised" (no
        announcement).
        """
        if not self._outage_active:
            # No outage in progress — nothing to announce.
            return
        self._outage_active = False
        if self._confirmed_connected:
            _LOGGER.info("Connection restored")
        # ``_confirmed_connected`` is set on the first
        # successful login (``_on_authenticated``); we don't flip
        # it here because the first-ever restore is silent
        # (it would be confusing to see "Connection restored"
        # before any "Connection lost").

    async def _on_authenticated(self) -> None:
        """This session has logged in (authwithtoken / gettoken / getjwt).

        Wakes the token refresh loop and reports the connection as
        usable: ``on_state("connected")`` and, after an outage, a single
        "Connection restored" INFO (the very first connect stays silent).
        """
        self._authenticated_event.set()
        self._confirmed_connected = True
        self._note_connection_restored()
        await self._signal_state(self._on_state, "connected")

    async def _signal_state(
        self,
        on_state: Optional[Callable[..., Any]],
        state: str,
    ) -> None:
        """Fire the optional ``on_state`` callback.

        The supervisor's owner (typically the integration's
        coordinator) passes ``on_state`` to :meth:`run` so
        entity availability can be updated without relying on
        a Task done-callback. ``on_state`` is a regular callable
        (sync) — the supervisor's hot path stays inline. The
        callback may also be a coroutine function; if so, we
        spawn the call in a tracked task so any exception is
        logged via the standard done-callback path.
        """
        if on_state is None:
            return
        try:
            result = on_state(state)
            if asyncio.iscoroutine(result):
                self._spawn_task(
                    self._await_on_state(result),
                    name=f"loxone.on-state-{state}",
                )
        except Exception as e:
            _LOGGER.warning("on_state callback raised: %s", e)

    async def _await_on_state(self, coro) -> None:
        """Drain a coroutine returned by ``on_state``.

        Extracted so :meth:`_signal_state` can hand the
        coroutine to :meth:`_spawn_task` cleanly.
        """
        await coro

    async def _safe_close(self) -> None:
        """Best-effort ``close()`` used by the supervisor.

        Closes the websocket and cancels pending background
        tasks WITHOUT setting the shutdown event. The public
        :meth:`close` sets the event to signal "this is a real
        close, don't come back"; the supervisor's close is
        just "the previous attempt died, prepare for the next
        one" and the next iteration of the retry loop must
        be allowed to run.

        Failures are logged at DEBUG (not WARNING) — the
        supervisor will retry regardless.
        """
        try:
            await self.close(_signal_shutdown=False)
            # ``close()`` marks the instance permanently closed
            # to prevent later accidental reuse. This invocation
            # is the supervisor's internal teardown between
            # attempts, so make the same instance reusable once
            # its socket and worker tasks have been cleaned up.
            # If a public close raced with the retry, keep the
            # terminal state; ``run()`` will observe the shutdown
            # event and exit.
            if not self._shutdown_event.is_set():
                self._closed = False
        except Exception as e:
            _LOGGER.debug("_safe_close: close() raised: %s", e)

    def _check_auth_response(
        self, mess_obj: Any, context: str
    ) -> None:
        """Inspect an LL envelope code and raise on hard auth failure.

        The five auth response handlers — ``getkey2``, ``getkey``,
        ``getvisusalt``, ``gettoken`` / ``getjwt``, and
        ``authwithtoken`` — used to log the error and continue.
        That meant a wrong-password restart would silently keep
        retrying, with the user only seeing the integration
        surface a "disconnected" state.

        This helper centralises the policy:

        - Code in :data:`LLRSP_UNAUTHORISED_CODES` (401, 4003) →
          raise :class:`LoxoneUnauthorisedError`. The supervisor
          propagates this as a hard auth failure.
        - Any other non-200 code → log at WARNING and return; the
          handler decides what to do (often nothing — those are
          transient).
        - ``code == 200`` (or missing) → no-op.

        The raised error is also stored on ``self._auth_failure``
        because the handlers run as fire-and-forget tasks: the
        exception would otherwise never leave ``_websocket_event``.
        The recv loop and the keepalive loop re-raise the stored
        error so the ``run()`` supervisor sees it.
        """
        code = getattr(mess_obj, "code", None)
        if code is None or code == 200:
            return
        if code in LLRSP_UNAUTHORISED_CODES:
            _LOGGER.warning(
                "Auth response in %s returned code %d "
                "(unauthorised) — escalating",
                context,
                code,
            )
            self._auth_failure = LoxoneUnauthorisedError(
                f"{context}: unauthorised (code {code})"
            )
            raise self._auth_failure
        _LOGGER.warning(
            "Auth response in %s returned non-ok code %d",
            context,
            code,
        )

    def _discard_queued_messages(
        self, reason: str, level: int = logging.DEBUG
    ) -> int:
        """Drop all queued outgoing commands (and pending secure commands).

        Returns the number of dropped messages.
        """
        dropped = 0
        while True:
            try:
                self._message_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._message_queue.task_done()
            dropped += 1
        dropped_secured = len(self._secured_queue)
        self._secured_queue.clear()
        if dropped or dropped_secured:
            _LOGGER.log(
                level,
                "Dropped %d queued command(s) and %d secure command(s): %s",
                dropped,
                dropped_secured,
                reason,
            )
        return dropped

    async def _process_message(self) -> NoReturn:
        """Process queued messages with graceful shutdown.

        This is the **high-throughput** outbound path: under load
        the Miniserver can push status updates at several hundred
        messages per second, and this consumer must not become a
        bottleneck. The pattern is a tight ``while`` loop that
        pops a message off the queue and immediately schedules
        the actual send as a background task. The two
        ``await asyncio.sleep(0)`` calls yield to the event loop
        so the spawned tasks actually start running instead of
        piling up in the task queue — without them the consumer
        could enqueue thousands of unstarted tasks before any of
        them get to run, which on a busy integration manifests as
        stale state, dropped value updates, and (in the worst
        case) the websocket hitting its keepalive timeout because
        no real work got done.

        Keep this fire-and-forget scheduling behavior under load
        testing before changing it: blocking the queue consumer
        on each send can let the message backlog grow.
        """
        _LOGGER.debug("Message processing task started")

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Use asyncio.Queue.get() with timeout
                    msg = await self._message_queue.get()
                    # Yield so the consumer doesn't starve the
                    # loop right after a wake-up.
                    await asyncio.sleep(0)
                    try:
                        # ``_spawn_task`` is a thin wrapper
                        # around ``asyncio.create_task`` that
                        # adds a done callback so unhandled
                        # exceptions are logged at WARNING
                        # instead of being silently swallowed.
                        # The throughput characteristics are
                        # identical to a bare ``create_task``.
                        self._spawn_task(
                            self._send_text_command(
                                msg.command, encrypted=msg.flag
                            ),
                            name="loxone.send-queued",
                        )
                        # Yield so the spawned send task gets
                        # a chance to start before the next
                        # ``get()`` call.
                        await asyncio.sleep(0)
                    except Exception as e:
                        _LOGGER.error(f"Error sending message: {e}")
                    finally:
                        # Mark task as done for queue.join()
                        self._message_queue.task_done()
                except asyncio.TimeoutError:
                    # Normal timeout, continue to check shutdown event
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    _LOGGER.error(f"Error in message processing loop: {e}")
                    await asyncio.sleep(0.1)  # Avoid tight loop on errors

        except asyncio.CancelledError:
            _LOGGER.debug(
                "Message processing task cancelled - processing remaining messages"
            )

            if not self.is_connected:
                # Nothing can reach the Miniserver any more; sending
                # would log one error per queued message.
                self._discard_queued_messages("connection closed")
                raise

            # Process any remaining messages before shutdown
            remaining_count = 0
            while not self._message_queue.empty():
                try:
                    msg = self._message_queue.get_nowait()
                    remaining_count += 1
                    try:
                        await self._send_text_command(msg.command, encrypted=msg.flag)
                    except Exception as e:
                        _LOGGER.error(f"Error processing final message: {e}")
                    finally:
                        self._message_queue.task_done()
                except asyncio.QueueEmpty:
                    break
                except Exception as e:
                    _LOGGER.error(f"Error draining message queue: {e}")

            if remaining_count > 0:
                _LOGGER.debug(
                    f"Processed {remaining_count} remaining messages during shutdown"
                )

            raise
        except Exception as e:
            _LOGGER.error(f"Message processing task failed: {e}")
            raise

    async def _do_start_listening(
        self,
        callback: Optional[Callable[[Any], Optional[Awaitable[None]]]],
        connection: LoxoneClientConnection,
    ) -> None:
        """Receive frames from ``connection`` and dispatch parsed
        events to ``callback`` / :meth:`_websocket_event`.

        State machine
        -------------

        Each Loxone event is ``(header, body...)`` — an 8-byte
        header followed by zero or more body frames whose total
        length is ``header.payload_length``. The body may span
        multiple websocket frames when the Miniserver chooses
        to chunk it.

        A header with ``estimated=True`` only announces an
        approximate size; per the spec ("An Estimated-Header is
        always followed by an exact Header") the exact header
        follows directly and carries the body. Estimated headers
        are therefore skipped.

        ``MessageHeader`` always populates ``message_type``,
        ``estimated`` and ``payload_length`` (zero-length body
        for non-0x03 frames) so this state machine can index
        them without conditional guards.

        Transitions
        -----------

        No header in progress:
          - 8-byte frame → parse as header. Estimated: skip it
            and wait for the exact header. If bodyless
            (payload_length == 0), dispatch immediately and stay
            "no header in progress". Otherwise enter
            "header in progress".
          - Non-8-byte frame → orphan; logged at ERROR, no state
            change.

        Header in progress (always an exact header):
          - Any frame is a body chunk — also an 8-byte one, which
            is a valid body (e.g. a short text) and must not be
            mistaken for the next header. Dispatch as soon as
            ``len(body_buffer) >= payload_length``.
        """
        # Set for O(1) membership tests on the external callback.
        callback_types = {
            MessageType.VALUE_STATES,
            MessageType.TEXT_STATES,
            MessageType.TEXT,
            MessageType.KEEPALIVE,
        }

        last_header: Optional[MessageHeader] = None
        body_buffer = bytearray()
        dispatched_since_yield = 0

        async def _run_callback(msg):
            try:
                await callback(msg.as_dict())
            except Exception as e:
                _LOGGER.error(f"Callback error: {e}", exc_info=True)

        async def _dispatch_body(header: MessageHeader, body: bytes) -> None:
            nonlocal dispatched_since_yield
            msg_type = header.message_type
            if msg_type == MessageType.TEXT:
                body = check_and_decode_if_needed(body)
            try:
                parsed_message = parse_message(body, msg_type)
            except Exception as e:
                _LOGGER.error(
                    f"Failed to parse body for {msg_type}: {e}"
                )
                return
            # Fire-and-forget the internal event processing and
            # the external callback. ``await`` here would block
            # the recv loop on every status update — at the
            # Miniserver's update rate that drops messages and
            # can starve the keepalive path. ``_spawn_task``
            # preserves fire-and-forget scheduling, tracks the
            # task for bulk pruning and reports unhandled
            # exceptions at WARNING. The recv loop yields in
            # bounded batches below.
            # Create the event task only for message types
            # ``_websocket_event`` branches on: for everything
            # else its coroutine runs straight into ``pass``, and
            # spawning plus later pruning that no-op task is the
            # most expensive thing left in this loop (+10.8%
            # measured, see ``_EVENT_HANDLED_TYPES``). Gave
            # ``_websocket_event`` a new branch? Add its message
            # type to ``_EVENT_HANDLED_TYPES``.
            if msg_type in _EVENT_HANDLED_TYPES:
                self._spawn_task(
                    self._websocket_event(parsed_message),
                    name=_EVENT_TASK_NAMES.get(msg_type, "loxone.event"),
                )
            if callback and msg_type in callback_types:
                self._spawn_task(
                    _run_callback(parsed_message),
                    name=_CALLBACK_TASK_NAMES.get(msg_type, "loxone.callback"),
                )
            # Let handlers run in bounded batches: yielding on
            # every event adds scheduler overhead, while never
            # yielding lets a buffered recv stream accumulate
            # unbounded pending tasks. The websocket read itself
            # naturally yields whenever it waits for network data.
            dispatched_since_yield += 1
            if dispatched_since_yield >= _DISPATCH_YIELD_BATCH:
                dispatched_since_yield = 0
                await asyncio.sleep(0)

        async def _dispatch_bodyless(header: MessageHeader) -> None:
            if header.message_type == MessageType.KEEPALIVE:
                # Fire-and-forget — same rationale as
                # ``_dispatch_body``. The keepalive callback
                # is the integration's "the websocket is alive"
                # heartbeat; awaiting it would serialise it
                # behind any in-flight user callback and
                # noticeably slow the keepalive loop.
                self._spawn_task(
                    _run_callback(Keepalive("")),
                    name="loxone.keepalive",
                )
                # Keepalives are infrequent (roughly every 30 s),
                # so yield immediately to deliver the liveness
                # callback without affecting the high-rate state
                # event path.
                await asyncio.sleep(0)
            # Other bodyless types (UNKNOWN, etc.) are logged at
            # DEBUG — there is no canonical handler for them.

        try:
            async for message in connection:
                if not connection or connection.state == connection.state.CLOSED:
                    raise LoxoneConnectionError("Connection is closed")

                # Liveness marker for the receive watchdog in
                # ``keep_alive()`` (the websockets ping/pong check is
                # disabled, so this is the only inbound-liveness
                # signal).
                self._last_frame_time = time.monotonic()

                # An auth handler may have recorded a hard credential
                # rejection (401 / 4003) on the fire-and-forget event
                # task, where it could not be propagated. Surface it
                # here so it reaches the ``run()`` supervisor instead
                # of being logged away inside ``_websocket_event``.
                if self._auth_failure is not None:
                    raise self._auth_failure

                message_length = len(message)

                if last_header is None:
                    # No body in progress. The frame must be a
                    # header (8 bytes). Anything else is an
                    # orphan.
                    if message_length != MESSAGE_HEADER_SIZE:
                        _LOGGER.error(
                            "Orphan body chunk of %d bytes "
                            "(no header in progress)",
                            message_length,
                        )
                        continue

                    new_header = parse_header(message)
                    if new_header.message_type == MessageType.OUT_OF_SERVICE:
                        raise LoxoneOutOfServiceException
                    if new_header.estimated:
                        # Size announcement only; the exact header
                        # follows and carries the body (spec).
                        _LOGGER.debug(
                            "Estimated header (%s, ~%d bytes); waiting "
                            "for the exact header",
                            new_header.message_type,
                            new_header.payload_length,
                        )
                        continue
                    if new_header.payload_length == 0:
                        # Bodyless: KEEPALIVE / UNKNOWN with zero
                        # length — dispatch and stay in "no header
                        # in progress".
                        await _dispatch_bodyless(new_header)
                        continue
                    last_header = new_header
                    body_buffer = bytearray()
                    continue

                # Header in progress: this frame is (part of) its
                # body, whatever its length - an 8-byte body is not
                # the next header. Fast path first: the body arrived
                # complete in one frame, which is the normal case
                # (the Miniserver sends header and body as separate
                # websocket messages). Dispatching the frame
                # directly avoids a bytearray extend plus two
                # slices plus a copy per event.
                if not body_buffer and len(message) == last_header.payload_length:
                    await _dispatch_body(last_header, message)
                    last_header = None
                    continue

                # Slow path: the body is split across frames —
                # accumulate until ``payload_length`` bytes arrived.
                body_buffer.extend(message)

                if len(body_buffer) >= last_header.payload_length:
                    body = bytes(body_buffer[:last_header.payload_length])
                    body_buffer = body_buffer[last_header.payload_length:]
                    await _dispatch_body(last_header, body)
                    last_header = None

            # Flush the final partial batch before surfacing a
            # clean close. In the normal long-running recv path,
            # batches have already been yielding periodically.
            await asyncio.sleep(0)

            # ``async for message in connection`` ended without
            # raising — the websocket was closed cleanly by the
            # peer (close code 1000). Surface that as
            # ``LoxoneConnectionClosedOk`` so the supervisor
            # can decide whether to reconnect.
            # Without this, the close would only surface 30 s
            # later when the keepalive timer timed out, by
            # which time the user had already seen
            # ``Connection lost`` as an ERROR.
            raise LoxoneConnectionClosedOk(
                "Websocket closed cleanly (recv loop ended without exception)"
            )
        except asyncio.CancelledError:
            _LOGGER.debug("Listening task cancelled")
            raise
        except (
            LoxoneTokenError,
            LoxoneOutOfServiceException,
            LoxoneConnectionError,
            LoxoneConnectionClosedOk,
            LoxoneUnauthorisedError,
            websockets.exceptions.ConnectionClosed,
        ):
            # Re-raise expected Loxone exceptions, and an abnormal close
            # (e.g. 1006 on a network drop): ``start_listening`` maps it
            # and the supervisor logs one WARNING per outage. The clean close is
            # deliberate control flow (raised above): the supervisor
            # turns it into a recoverable error and reconnects. The
            # credential rejection is deliberate control flow too (the
            # ``run()`` supervisor must see it to stop retrying).
            # Falling through to the catch-all would log an ERROR with
            # a traceback on every clean shutdown, unload or reconnect.
            raise
        except Exception as e:
            _LOGGER.error(f"Unexpected error in listening loop: {e}", exc_info=True)
            raise

    async def _get_with_retry(
        self,
        url: str,
        connector: LoxoneAsyncHttpClient,
        *,
        max_tries: int = RECONNECT_TRIES,
        base_delay: float = RECONNECT_DELAY,
        max_delay: float = MAX_RECONNECT_DELAY,
    ) -> tuple[bytes, str]:
        """Fetch ``url`` via ``connector`` with bounded exponential backoff.

        Used for the three bootstrap GETs in :meth:`open` —
        ``CMD_GET_API_KEY``, ``LOXAPPPATH`` and ``CMD_GET_PUBLIC_KEY`` —
        which all have to succeed before the websocket handshake can
        begin. Transient network errors (Miniserver briefly
        unreachable, a TLS hiccup, an aiohttp timeout) are retried
        with backoff ``min(base_delay * 2**attempt, max_delay)`` and
        a small jitter so multiple HA instances reconnecting after
        the same outage don't lock-step.

        Catches the error classes that indicate "Miniserver
        unreachable, try again":

        - ``LoxoneServiceUnAvailableError`` (HTTP 503)
        - ``ConnectionError`` (DNS / TCP refused)
        - ``OSError`` (lower-level socket error)
        - ``asyncio.TimeoutError`` and the stdlib ``TimeoutError``
        - ``aiohttp.ClientError`` (catch-all for aiohttp's transient
          client-side failures)

        Auth and parse errors are NOT retried: those are raised by
        the LL envelope parse and propagate immediately.

        Returns ``(body_bytes, final_url)`` where ``final_url`` is
        the URL after any redirect (used to discover the canonical
        base URL on Cloud-DNS-flavoured Miniservers).
        """
        last_exc: BaseException | None = None
        for attempt in range(max_tries):
            try:
                # ``async with`` releases the aiohttp response on
                # exit; we capture the body and the final URL as
                # locals so they survive the block.
                body = b""
                final_url = ""
                async with connector.get(url) as resp:
                    body = await resp.content.read()
                    final_url = str(resp.url)
                if attempt > 0:
                    _LOGGER.debug(
                        "GET %s succeeded on attempt %d/%d",
                        url,
                        attempt + 1,
                        max_tries,
                    )
                return body, final_url
            except (
                LoxoneServiceUnAvailableError,
                ConnectionError,
                OSError,
                asyncio.TimeoutError,
                TimeoutError,
                aiohttp.ClientError,
            ) as e:
                last_exc = e
                if attempt < max_tries - 1:
                    # Exponential backoff with ±20% jitter, capped at
                    # ``max_delay``.  ``random.uniform`` adds the
                    # jitter; using a local random instance keeps
                    # the helper deterministic in tests via
                    # ``random.seed``.
                    import random

                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = delay * 0.2 * (2 * random.random() - 1)
                    sleep_for = max(0.0, delay + jitter)
                    _LOGGER.debug(
                        "GET %s failed (attempt %d/%d): %s; "
                        "retrying in %.1fs",
                        url,
                        attempt + 1,
                        max_tries,
                        e,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue
                # Final attempt failed.
                break
        # All attempts exhausted.
        assert last_exc is not None
        raise last_exc

    async def open(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        connect_websocket: bool = True,
    ) -> LoxoneClientConnection | None:
        """Bootstrap over HTTP and (by default) open the websocket.

        With ``connect_websocket=False`` only the HTTP bootstrap and
        the session-key generation run; ``structure_file`` is
        available afterwards, and the websocket is opened by the next
        :meth:`start_listening` right before the key exchange. Use
        this when there is a delay between bootstrap and listening
        (e.g. Home Assistant setting up its platforms): the Miniserver
        closes a websocket that is not authenticated within a few
        seconds (issue #527).
        """

        if self._closed:
            raise RuntimeError("Cannot open a closed connection")

        connector = None
        try:
            connector = LoxoneAsyncHttpClient(
                url=self.url,
                username=self.username,
                password=self.password,
                scheme=self.scheme,
                verify_ssl=self.verify_ssl,
                session=session,
            )
            api_key_redirect: str | None = None
            api_key_data: bytes = b""
            # Bounded exponential-backoff retry; transient network
            # errors are retried with backoff ``min(base * 2**n, max)``
            # plus ±20% jitter.  See :meth:`_get_with_retry`.
            api_key_data, api_key_redirect = await self._get_with_retry(
                CMD_GET_API_KEY, connector
            )
            # ``_get_with_retry`` returns the body bytes and the
            # final URL after any redirect.  The previous inline loop
            # used ``async with`` to release the aiohttp response, so
            # by the time we reach here the body has been fully read
            # and the response is closed.
            data = api_key_data

            try:
                _value = LLResponse(data).value
            except Exception as e:
                raise ValueError(f"Invalid API key response format: {e}") from e

            # The json returned by the miniserver is invalid. It contains " and '.
            # We need to normalize it
            try:
                value = json.loads(_value.replace("'", '"'))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in API key response: {e}") from e
            except Exception as e:
                raise ValueError(f"Failed to parse API key response: {e}") from e

            # Validate response structure
            if not isinstance(value, dict):
                raise ValueError(f"Expected dict response, got {type(value)}")

            version_str = value.get("version")
            if version_str:
                try:
                    self.miniserver_version = [int(x) for x in version_str.split(".")]
                except (ValueError, AttributeError) as e:
                    _LOGGER.warning(f"Invalid version format '{version_str}': {e}")
                    self.miniserver_version = []
            else:
                _LOGGER.warning("No version in API response")
                self.miniserver_version = []

            self.miniserver_serial = value.get("snr", "")
            local = value.get("local", True)

            if not local:
                try:
                    connector.base_url = (
                        api_key_redirect or connector.base_url
                    ).replace(CMD_GET_API_KEY, "")
                    new_scheme, new_host = parse_loxone_url(connector.base_url)
                    if new_scheme != self.scheme or new_host != self.url:
                        self._apply_url(new_scheme, new_host)
                except Exception as e:
                    _LOGGER.warning(f"Failed to update URL for remote access: {e}")

            # Get the structure file.  Use ``_get_with_retry`` so a
            # transient network blip during the structure-file fetch
            # doesn't fail the whole open().
            data, _ = await self._get_with_retry(LOXAPPPATH, connector)

            try:
                # ``LoxAPP3.json`` is the full Miniserver structure
                # file — often a few megabytes. Run ``json.loads`` off
                # the event loop when an executor was supplied (the
                # coordinator passes ``hass.async_add_executor_job``).
                if self.executor is not None:
                    self.structure_file = await self.executor(
                        json.loads, data
                    )
                else:
                    self.structure_file = json.loads(data)
                self.structure_file["softwareVersion"] = (
                    self.miniserver_version
                )  # FIXME Legacy use only. Need to fix pyloxone
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in structure file: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Failed to read structure file: {e}") from e

            # Get the public key.  Same retry helper as above.
            pk_data_text, _ = await self._get_with_retry(
                CMD_GET_PUBLIC_KEY, connector
            )

            try:
                pk = LLResponse(pk_data_text).value
            except Exception as e:
                raise ValueError(f"Invalid public key response format: {e}") from e

            if not pk:
                raise ValueError("Empty public key received")

            # Loxone returns a certificate instead of a key
            self._public_key = pk.replace(
                "-----BEGIN CERTIFICATE-----", "-----BEGIN PUBLIC KEY-----\n"
            ).replace("-----END CERTIFICATE-----", "\n-----END PUBLIC KEY-----\n")
        except LoxoneServiceUnAvailableError:
            raise
        except _TRANSIENT_NETWORK_ERRORS as e:
            # Miniserver unreachable: expected while it reboots or the
            # network is down. The caller reports it (setup: "Will retry
            # automatically"; ``run()``: one "Connection lost" WARNING per
            # outage) - an ERROR with traceback on every attempt is noise.
            _LOGGER.debug("Failed to initialize connection: %s", e)
            raise
        except Exception as e:
            _LOGGER.error(f"Failed to initialize connection: {e}", exc_info=True)
            raise
        finally:
            # Async httpx client must always be closed
            if session is None and connector:
                try:
                    await connector.session.close()
                except Exception as e:
                    _LOGGER.warning(f"Error closing HTTP session: {e}")

        # Init RSA cipher
        try:
            if not self._public_key:
                raise ValueError("Public key is empty")

            try:
                rsa_key = RSA.importKey(self._public_key)
            except (ValueError, IndexError, TypeError) as e:
                raise ValueError(f"Invalid RSA public key format: {e}") from e

            # RSA PKCS1 has been broken for a long time. Loxone uses it anyway
            rsa_cipher = PKCS1_v1_5.new(rsa_key)
            _LOGGER.debug("init_rsa_cipher successfully...")
        except Exception as exc:
            _LOGGER.error(f"Error creating RSA cipher: {exc}")
            raise LoxoneException(f"RSA cipher initialization failed: {exc}") from exc

        # Generate session key
        try:
            if not self._aes_key or not self._iv:
                raise RuntimeError("Encryption keys not initialized")

            aes_key = self._aes_key.hex()
            iv = self._iv.hex()
            session_key = f"{aes_key}:{iv}".encode("utf-8")

            try:
                encrypted = rsa_cipher.encrypt(session_key)
                if not encrypted:
                    raise ValueError("RSA encryption returned empty result")
                self._session_key = b64encode(encrypted)
            except Exception as e:
                raise RuntimeError(f"RSA encryption failed: {e}") from e

            _LOGGER.debug("generate_session_key successfully...")
        except Exception as exc:
            _LOGGER.error(f"Error generating session key: {exc}")
            raise LoxoneException(f"Session key generation failed: {exc}") from exc

        if not connect_websocket:
            self._websocket_deferred = True
            return None
        return await self._connect_websocket()

    async def _connect_websocket(self) -> LoxoneClientConnection:
        """Open the websocket after a completed :meth:`open` bootstrap.

        The caller must send the key exchange right after this
        returns; the Miniserver closes a websocket that is not
        authenticated within a few seconds (issue #527).
        """
        # generate first salt
        try:
            self._generate_salt()
        except Exception as e:
            _LOGGER.error(f"Failed to generate initial salt: {e}")
            raise

        # Establish websocket connection
        try:
            base_url = build_loxone_url(self.scheme, self.url)

            try:
                websocket_options = self._build_websocket_options()
                if ssl_context := self._websocket_ssl_context():
                    websocket_options["ssl"] = ssl_context

                connection = await asyncio.wait_for(
                    wslib.connect(base_url, **websocket_options),
                    timeout=(self.timeout or TIMEOUT) * 2,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timeout connecting to websocket at {base_url}")
            except websockets.exceptions.InvalidURI as e:
                raise ValueError(f"Invalid websocket URI '{base_url}': {e}") from e
            except websockets.exceptions.WebSocketException as e:
                raise LoxoneConnectionError(f"Websocket connection failed: {e}") from e
            except OSError as e:
                raise ConnectionError(
                    f"Network error connecting to {base_url}: {e}"
                ) from e
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error connecting to websocket: {e}"
                ) from e

            _LOGGER.debug(f"Websocket connection established to {base_url}")
            # Store the websocket on the instance. Anything that fails
            # between here and the return propagates as an exception
            # without mutating ``self.connection`` (the previous value
            # stays — typically ``None``).
            # Reset the receive watchdog *after* the websocket is up:
            # a slow bootstrap (apiKey / LoxAPP3 / publicKey) must not
            # look like a stale connection to the first keepalive
            # cycle.
            self._last_frame_time = time.monotonic()
            self._auth_failure = None
            # A new websocket is a new, unauthenticated session: the
            # token refresh loop and ``async_refresh_token`` must wait
            # for this session's authwithtoken / getjwt reply. Left set
            # from the previous session, the refresh loop would send
            # refreshjwt before the login (with an expired token after a
            # long outage).
            self._authenticated_event.clear()
            self.connection = connection
            self._websocket_deferred = False
            # "connected" / "Connection restored" are reported only once
            # this session has logged in (``_on_authenticated``): an open
            # but unauthenticated socket is not usable yet, and reporting
            # it made entities flip to available and back when the login
            # then failed.
            return connection

        except _TRANSIENT_NETWORK_ERRORS as e:
            # See ``open()``: reported once by the caller.
            _LOGGER.debug("Failed to establish websocket connection: %s", e)
            raise
        except Exception as e:
            _LOGGER.error(f"Failed to establish websocket connection: {e}")
            raise

    def _spawn_task(self, coro, name: str) -> asyncio.Task:
        """Schedule ``coro`` as a tracked background task.

        The task is added to ``self._tasks``; once the set grows past
        :data:`_TASK_PRUNE_THRESHOLD` entries, :meth:`_prune_tasks`
        drops the finished ones and logs any unhandled exception at
        WARNING (a bare ``asyncio.create_task`` would silently
        swallow it).

        Bookkeeping is deliberately **bulk** and not a per-task
        done callback. A done callback makes the event loop schedule
        one extra callback per spawned task — ``call_soon`` + a
        ``Handle`` + a ``Context.run`` — which on a busy Miniserver
        (hundreds of spawned tasks per second) measured at ~10 % of
        the total recv/dispatch throughput. Amortised pruning costs
        a set membership test per spawn instead.

        Use this instead of ``asyncio.create_task`` for any
        fire-and-forget coroutine. For long-lived coroutines that
        the connection owns and waits on (the recv loop, the
        keepalive loop, etc.) keep using ``self._pending_task`` —
        those are awaited in ``close()`` and shut down
        deterministically.
        """
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        if len(self._tasks) > _TASK_PRUNE_THRESHOLD:
            self._prune_tasks()
        return task

    def _prune_tasks(self) -> None:
        """Drop finished tasks from ``self._tasks``, logging their exceptions.

        Runs only when the set grows past :data:`_TASK_PRUNE_THRESHOLD`,
        so the per-spawn cost stays O(1) amortised. Retrieving the
        exception here is what keeps ``asyncio`` from later reporting
        "Task exception was never retrieved"; ``close()`` prunes again
        so nothing is left unreported on shutdown.
        """
        if not self._tasks:
            return
        pending: set[asyncio.Task] = set()
        for task in self._tasks:
            if not task.done():
                pending.add(task)
                continue
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                _LOGGER.warning(
                    "Background task %r raised: %s",
                    task.get_name(),
                    exc,
                    exc_info=exc,
                )
        self._tasks = pending

    async def close(self, _signal_shutdown: bool = True) -> None:
        """Gracefully close the connection and drain message queues.

        ``_signal_shutdown`` (default ``True``) controls whether
        the shutdown event is set as part of the close. The
        supervisor's :meth:`_safe_close` passes ``False`` so the
        next iteration of its retry loop can run — the
        shutdown event is "this is a real close, don't come
        back" and the supervisor's close is "the previous
        attempt died, prepare for the next one". The
        ``_`` prefix marks it as private; the public
        :func:`coordinator.async_cleanup` path uses the default.
        """
        if _signal_shutdown:
            # Signal shutdown to all tasks first - also when a
            # supervisor ``_safe_close()`` is already closing
            # (``_closed`` set): returning early without it let the
            # supervisor reset ``_closed`` and reconnect after a
            # real close. The supervisor's retry loop relies on this
            # NOT being set for its own ``_safe_close()``.
            self._shutdown_event.set()

        if self._closed:
            _LOGGER.debug("Connection already closed")
            return

        _LOGGER.debug("Closing connection...")
        self._closed = True
        # A reconnect after this close re-runs the full ``open()``
        # bootstrap, as before the websocket could be deferred.
        self._websocket_deferred = False

        # Drop any pending secure commands — they would never reach
        # the Miniserver and any stale visual hash should not be
        # reused across a reconnect.
        self._secured_queue.clear()

        # Wait for message queue to drain (with timeout) - only while
        # the socket is still open; on a dead connection nothing can be
        # sent and waiting only delays the teardown.
        if self._message_queue and self.is_connected:
            queue_size = self._message_queue.qsize()
            if queue_size > 0:
                _LOGGER.debug(f"Waiting for {queue_size} messages to be processed...")
                try:
                    await asyncio.wait_for(self._message_queue.join(), timeout=5.0)
                    _LOGGER.debug("All messages processed")
                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        f"Timeout waiting for message queue to drain ({queue_size} messages remaining)"
                    )

        # Cancel all pending tasks
        if self._pending_task:
            _LOGGER.debug(f"Cancelling {len(self._pending_task)} pending tasks...")
            for task in self._pending_task:
                try:
                    if task and not task.done():
                        task.cancel()
                except Exception as e:
                    _LOGGER.warning(f"Error cancelling task: {e}")

            # Wait for tasks to finish or cancel
            if self._pending_task:
                try:
                    await asyncio.gather(*self._pending_task, return_exceptions=True)
                except Exception as e:
                    _LOGGER.warning(f"Error waiting for tasks to complete: {e}")

            # clear pending tasks
            self._pending_task = []

        # Cancel any tracked background tasks spawned via
        # :meth:`_spawn_task`. These are fire-and-forget; pruning
        # first reports the exceptions of any that already finished
        # so nothing is lost when the connection goes away.
        self._prune_tasks()
        if self._tasks:
            _LOGGER.debug(
                f"Cancelling {len(self._tasks)} background tasks..."
            )
            for task in list(self._tasks):
                try:
                    if not task.done():
                        task.cancel()
                except Exception as e:
                    _LOGGER.warning(f"Error cancelling background task: {e}")
            # Wait briefly for the cancellations to complete.
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                _LOGGER.debug("Background tasks did not cancel within 2s")
            self._tasks.clear()

        # Close websocket connection if present
        if self.connection:
            try:
                if not self.connection.state == self.connection.state.CLOSED:
                    await asyncio.wait_for(self.connection.close(), timeout=5.0)
                    _LOGGER.debug("Websocket connection closed")
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout closing websocket connection")
            except Exception as e:
                _LOGGER.warning(f"Error closing websocket connection: {e}")
            finally:
                self.connection = None

        _LOGGER.debug("Connection closed successfully.")

    async def run(
        self,
        on_state: Optional[Callable[..., Any]] = None,
        callback: Optional[Callable[..., Any]] = None,
        *,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        """Supervise the listen loop with bounded exponential backoff.

        The previous design was: call ``start_listening()`` and
        react to the Task's done-callback from outside. That
        model forced the integration to reload the whole config
        entry on every transient drop, which cost a few seconds
        of "disconnected" entity state and a hard restart of
        every Miniserver-side subscription.

        This method owns the listen loop on the same instance
        (a single websocket / RSA / token state) and
        retries recoverable errors with exponential backoff:

          - :class:`LoxoneUnauthorisedError` — propagates (the
            integration will surface a config-entry error
            instead of looping forever).
          - :class:`LoxoneAuthEscalatedError` — propagates after
            ``TOKEN_REFRESH_MAX_FAILURES`` failed refresh cycles.
          - :attr:`RETRYABLE_SESSION_ERRORS` — the explicit list
            below (``LoxoneTokenError`` included: it is the expected
            first leg of the token-expiry self-heal, where a
            reconnect re-authenticates with the password),
            ``OSError``, ``TimeoutError``,
            ``websockets.exceptions.ConnectionClosed``:
            close, sleep ``min(base·2^n, max_delay)`` with ±20%
            jitter, retry.
          - Anything else — log ERROR, propagate.

        ``on_state(state)`` (optional) is fired with one of
        ``"connected"``, ``"disconnected"``, ``"failed"`` so
        the integration can update entity availability without
        a done callback. ``callback`` is forwarded to
        :meth:`start_listening` as the per-message callback.

        ``close()`` ends the loop cleanly (sets the shutdown
        event). The next ``start_listening`` returning
        normally (the clean-shutdown path) also exits
        ``run()`` without retrying.
        """
        # Publish the callback so ``open()`` can signal "connected"
        # as soon as the websocket is up (without knowing about us).
        self._on_state = on_state
        attempt = 0
        try:
            while not self._shutdown_event.is_set():
                try:
                    # ``start_listening`` calls ``open()`` if
                    # needed and blocks until the connection is
                    # closed. We pass ``callback`` straight through.
                    await self.start_listening(callback=callback)
                    # ``start_listening`` returned without raising
                    # — that means ``close()`` was called
                    # (shutdown). Exit the loop without retrying.
                    await self._signal_state(on_state, "disconnected")
                    return
                except LoxoneUnauthorisedError as e:
                    _LOGGER.error(
                        "Auth failed; not retrying: %s", e
                    )
                    await self._signal_state(on_state, "failed")
                    self._note_connection_lost(f"unauthorised: {e}")
                    raise
                except LoxoneAuthEscalatedError as e:
                    _LOGGER.error(
                        "Token refresh failed repeatedly; not retrying: %s",
                        e,
                    )
                    await self._signal_state(on_state, "failed")
                    self._note_connection_lost(f"auth escalated: {e}")
                    raise
                except self.RETRYABLE_SESSION_ERRORS as e:
                    self._note_connection_lost(
                        f"session error: {e}"
                    )
                    await self._signal_state(on_state, "disconnected")
                    attempt += 1
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    jitter = delay * 0.2 * (2 * random.random() - 1)
                    sleep_for = max(0.0, delay + jitter)
                    _LOGGER.debug(
                        "run(): session error (attempt %d): %s; "
                        "retrying in %.1fs",
                        attempt, e, sleep_for,
                    )
                    await self._safe_close()
                    # Yield so the entity availability callback
                    # gets a chance to run before we sleep.
                    await asyncio.sleep(0)
                    await asyncio.sleep(sleep_for)
                    continue
                except Exception as e:
                    _LOGGER.error(
                        "run(): unexpected error: %s",
                        e, exc_info=True,
                    )
                    await self._signal_state(on_state, "failed")
                    await self._safe_close()
                    raise
        finally:
            # The callback is only valid for the lifetime of the
            # supervisor loop; ``open()`` must not signal "connected"
            # once ``run()`` has returned.
            self._on_state = None
        # Shutdown requested before the first attempt finished.
        await self._signal_state(on_state, "disconnected")

    async def send_websocket_command(
        self, device_uuid: str, value: Union[str, int, float]
    ):
        """Send a websocket command to the Miniserver.

        value may be a str, int or float — it will be converted to string when sent.
        """

        if not device_uuid or not isinstance(device_uuid, str):
            raise ValueError("device_uuid must be a non-empty string")

        # if value is None or not isinstance(value, (str, int, float)):
        #    raise ValueError("value must be a string, int, or float")

        try:
            command = "jdev/sps/io/{}/{}".format(device_uuid, str(value))
            _LOGGER.debug("Call send_websocket_command: {}".format(command))

            try:
                # Use put_nowait with QueueFull exception handling for backpressure
                self._message_queue.put_nowait(
                    MessageForQueue(command=command, flag=True)
                )
            except asyncio.QueueFull:
                _LOGGER.error(
                    f"Message queue full (size: {self._message_queue.maxsize}), dropping command for {device_uuid}"
                )
                raise RuntimeError("Message queue is full, cannot send command")
        except Exception as e:
            _LOGGER.error(f"Failed to send websocket command: {e}")
            raise

    async def send_secured_websocket_command(
        self, device_uuid: str, value: Union[str, int, float], code: str
    ):
        if not device_uuid or not isinstance(device_uuid, str):
            raise ValueError("device_uuid must be a non-empty string")
        if value is None or not isinstance(value, (str, int, float)):
            raise ValueError("value must be a string, int, or float")
        if not code or not isinstance(code, str):
            raise ValueError("code must be a non-empty string")

        try:
            command = f"{CMD_GET_VISUAL_PASSWD}{self._encoded_username}"
            # Lazy %-args, same rationale as ``_send_text_command``.
            _LOGGER.debug("Call send_secured_websocket_command: %s", command)

            # Stash the (device_uuid, value, code) tuple on the
            # secured-queue deque. The Miniserver's
            # ``getvisusalt`` response releases it via ``_send_next_secured_command``,
            # which builds the wire command text using the
            # visual hash and forwards it to ``_message_queue``.
            # Replaces the previous opaque-coroutine-on-a-Queue
            # design — see :class:`SecuredCommand`.
            self._secured_queue.append(
                SecuredCommand(device_uuid, value, code)
            )
            self._message_queue.put_nowait(
                MessageForQueue(command=command, flag=True)
            )
        except Exception as e:
            _LOGGER.error(f"Failed to send secured websocket command: {e}")
            raise

    async def send_secured__websocket_command(
        self, device_uuid: str, value: Union[str, int, float], code: str
    ):
        # Deprecated alias for ``send_secured_websocket_command`` — the
        # double-underscore form was a typo kept for backwards
        # compatibility with external scripts that imported it directly.
        # Internal callers should use ``send_secured_websocket_command``.
        _LOGGER.debug(
            "send_secured__websocket_command is deprecated; "
            "use send_secured_websocket_command"
        )
        return await self.send_secured_websocket_command(device_uuid, value, code)

    async def _websocket_event(self, message: dict[str, Any] | BaseMessage) -> None:
        """Handle websocket event."""
        if message is None:
            _LOGGER.warning("Received None message")
            return

        mess_obj = None
        try:
            if isinstance(message, str):
                if message.startswith("{"):
                    try:
                        mess_obj = parse_message(
                            message,
                            (
                                self.message_header.message_type
                                if self.message_header
                                else None
                            ),
                        )
                    except Exception as e:
                        _LOGGER.error(f"Failed to parse string message: {e}")
                        return
            elif isinstance(message, bytes):
                try:
                    mess_obj = parse_message(
                        message,
                        (
                            self.message_header.message_type
                            if self.message_header
                            else None
                        ),
                    )
                except Exception as e:
                    _LOGGER.error(f"Failed to parse bytes message: {e}")
                    return
            elif isinstance(message, BaseMessage):
                mess_obj = message
            else:
                _LOGGER.warning(f"Unexpected message type: {type(message)}")
                return

            if mess_obj is None:
                return

            # Decrypt if needed
            if (
                hasattr(mess_obj, "control")
                and mess_obj.control
                and mess_obj.control.find("/enc/") > -1
            ):
                try:
                    mess_obj.control = self._decrypt(mess_obj.control)
                except Exception as e:
                    _LOGGER.error(f"Failed to decrypt control message: {e}")
                    return

            # Handle key exchange
            if isinstance(mess_obj, TextMessage) and "keyexchange" in mess_obj.message:
                _LOGGER.debug("Key exchange with miniserver...")
                command = f"{CMD_GET_KEY_AND_SALT}/{self._encoded_username}"
                try:
                    # Use put() for critical protocol messages
                    await self._message_queue.put(MessageForQueue(command, True)),
                except asyncio.TimeoutError:
                    _LOGGER.error("Timeout queueing key exchange command")

            # Handle getkey2
            elif isinstance(mess_obj, TextMessage) and "getkey2" in mess_obj.message:
                _LOGGER.debug("Got get key2")
                try:
                    self._check_auth_response(mess_obj, "getkey2")
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")

                    self._key = value_dict.get("key", "")
                    self._user_salt = value_dict.get("salt", "")
                    self._hash_alg = value_dict.get("hashAlg", "SHA1")

                    if not self._key:
                        raise ValueError("Key is empty")
                    if not self._user_salt:
                        raise ValueError("Salt is empty")

                    if self._token.seconds_to_expire() > 100:
                        _LOGGER.debug("Use old token...")
                        token_hash = self._hash_token()
                        if token_hash is None:
                            raise RuntimeError("Failed to hash token")
                        command = "{}{}/{}".format(
                            CMD_AUTH_WITH_TOKEN, token_hash, self._encoded_username
                        )
                        await self._message_queue.put(MessageForQueue(command, True))
                    else:
                        _LOGGER.debug("Acquire new token...")
                        new_hash = self._hash_credentials()
                        if new_hash is None:
                            raise RuntimeError("Failed to hash credentials")

                        # Request new Token
                        if self.miniserver_version < [10, 2]:
                            command = f"{CMD_REQUEST_TOKEN}/{new_hash}/{self._encoded_username}/{TOKEN_PERMISSION}/edfc5f9a-df3f-4cad-9dddcdc42c732b82/pyloxone_api"
                        else:
                            command = f"{CMD_REQUEST_TOKEN_JSON_WEB}/{new_hash}/{self._encoded_username}/{TOKEN_PERMISSION}/edfc5f9a-df3f-4cad-9dddcdc42c732b82/pyloxone_api"
                        await self._message_queue.put(MessageForQueue(command, True))

                except LoxoneUnauthorisedError:
                    # Hard credential rejection — must reach the
                    # ``run()`` supervisor, not just the log.
                    raise
                except KeyError as e:
                    _LOGGER.error(f"Missing key in getkey2 response: {e}")
                except asyncio.TimeoutError:
                    _LOGGER.error("Timeout queueing getkey2 command")
                except Exception as e:
                    _LOGGER.error(f"Error processing getkey2: {e}")

            # Handle getkey
            elif isinstance(mess_obj, TextMessage) and "getkey" in mess_obj.message:
                _LOGGER.debug("Got get getkey")
                try:
                    self._check_auth_response(mess_obj, "getkey")
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")
                    self._key = value_dict.get("value", "")
                    # Signal that key has been updated
                    if self._key_update_event is not None:
                        self._key_update_event.set()

                except LoxoneUnauthorisedError:
                    # Hard credential rejection — must reach the
                    # ``run()`` supervisor, not just the log.
                    raise
                except Exception as e:
                    _LOGGER.error(f"Error processing getkey: {e}")

            # Handle visual salt
            elif (
                isinstance(mess_obj, TextMessage) and "getvisusalt" in mess_obj.message
            ):
                try:
                    self._check_auth_response(mess_obj, "getvisusalt")
                    code = getattr(mess_obj, "code", None)
                    if code not in (None, 200):
                        raise ValueError(f"getvisusalt returned code {code}")
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")
                    # do NOT touch ``self._key`` here. The
                    # ``value`` field of the getvisusalt response is
                    # the *visual-hash* AES key (used only for
                    # secure-command HMACs); ``self._key`` is the
                    # *session* AES key from ``getkey2``. They are
                    # completely different keys and the previous
                    # assignment here clobbered ``self._key`` on
                    # every secured-command cycle, breaking all
                    # subsequent session-key encryption
                    # (``_hash_credentials`` would compute the wrong
                    # HMAC). ``read_user_salt_response`` below
                    # already stores the visual-hash key on
                    # ``key_and_salt.key`` — that's the only place
                    # it needs to live.

                    key_and_salt = LxJsonKeySalt()
                    key_and_salt.read_user_salt_response(mess_obj.message)
                    key_and_salt.time_elapsed_in_seconds = time_elapsed_in_seconds()
                    self._visual_hash = key_and_salt

                except LoxoneUnauthorisedError:
                    # Hard credential rejection — must reach the
                    # ``run()`` supervisor, not just the log. The
                    # command this reply belongs to is not sent.
                    self._drop_next_secured_command("unauthorised")
                    raise
                except Exception as e:
                    _LOGGER.error(f"Error processing visual salt: {e}")
                    # This reply's command must not run later with
                    # the next command's reply.
                    self._drop_next_secured_command(str(e))
                else:
                    # One reply releases exactly one command; see
                    # ``_send_next_secured_command``.
                    await self._send_next_secured_command()

            # Handle token response
            elif isinstance(mess_obj, TextMessage) and (
                "gettoken" in mess_obj.message or "getjwt" in mess_obj.message
            ):
                try:
                    self._check_auth_response(mess_obj, "gettoken")
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")

                    self._token.token = value_dict.get("token")
                    self._token.valid_until = value_dict.get("validUntil", 0)
                    self._token.key = value_dict.get("key", "")
                    self._token.hash_alg = self._hash_alg

                    if "unsecurePass" in value_dict:
                        self._token.unsecure_password = value_dict.get(
                            "unsecurePass", False
                        )

                    if not self._token.token:
                        raise ValueError("Received empty token")

                    # Signal the refresh loop that the token is
                    # now populated. ``check_refresh_token`` was
                    # blocked on this event; it can now start its
                    # 50%-of-lifetime countdown.
                    await self._on_authenticated()

                    # Notify the integration (e.g. the HA
                    # coordinator) that the token changed so it
                    # can persist the new value.
                    self._signal_token_changed()

                    await self._message_queue.put(
                        MessageForQueue(f"{CMD_ENABLE_UPDATES}", True)
                    )

                except LoxoneUnauthorisedError:
                    # Hard credential rejection — must reach the
                    # ``run()`` supervisor, not just the log.
                    raise
                except KeyError as e:
                    _LOGGER.error(f"Missing key in token response: {e}")
                except asyncio.TimeoutError:
                    _LOGGER.error("Timeout queueing enable updates command")
                except Exception as e:
                    _LOGGER.error(f"Error processing token: {e}")

            # Handle auth with token
            elif isinstance(mess_obj, TextMessage) and (
                "authwithtoken" in mess_obj.message
            ):
                if mess_obj.code == 401:
                    # Issue #514: 401 here is the *expected* first leg of the
                    # token-expiry self-heal flow — the cached token is
                    # stale, the integration resets it and falls back to
                    # username/password auth. Log at DEBUG so the user only
                    # sees ERROR if the fallback also fails.
                    _LOGGER.debug("Token authentication failed (401); resetting and re-authenticating")
                    self.reset_token()
                    self._reconnect_event.set()
                else:
                    _LOGGER.debug("Got message authwithtoken")
                    try:
                        # Cached-token authentication is a successful
                        # authentication path too. Signal the refresh
                        # loop and manual refresh service just as the
                        # gettoken/getjwt handler does.
                        if mess_obj.code == 200:
                            await self._on_authenticated()
                        await self._message_queue.put(
                            MessageForQueue(f"{CMD_ENABLE_UPDATES}", True)
                        )
                    except asyncio.TimeoutError:
                        _LOGGER.error("Timeout queueing authwithtoken command")

            # Handle token refresh
            elif isinstance(mess_obj, TextMessage) and (
                "refreshjwt" in mess_obj.message or "refresh" in mess_obj.message
            ):
                _LOGGER.debug(f"Got token refresh response")
                try:
                    self._check_auth_response(mess_obj, "token refresh")
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")

                    token = value_dict.get("token")
                    valid_until = value_dict.get("validUntil")

                    if not token:
                        raise ValueError("Received empty token in refresh")
                    if valid_until is None:
                        raise ValueError("Missing validUntil in refresh")

                    self._token.token = token
                    self._token.valid_until = valid_until

                    if "unsecurePass" in value_dict:
                        self._token.unsecure_password = value_dict.get(
                            "unsecurePass", False
                        )

                    _LOGGER.debug(
                        "Token refreshed successfully, valid until: %s (%s)",
                        valid_until,
                        _format_loxone_token_expiration(valid_until),
                    )

                    # Notify the integration that the token
                    # changed so the new value can be persisted.
                    self._signal_token_changed()
                    self._token_refresh_error = None
                    self._token_refresh_event.set()

                except LoxoneUnauthorisedError as e:
                    # Hard credential rejection: unblock the awaiting
                    # refresh with the error and escalate to the
                    # supervisor instead of just logging it.
                    self._token_refresh_error = e
                    self._token_refresh_event.set()
                    raise
                except KeyError as e:
                    self._token_refresh_error = LoxoneTokenError(
                        f"Malformed token refresh response: {e}"
                    )
                    self._token_refresh_event.set()
                    _LOGGER.error(
                        f"Missing key in token refresh response: {e}. "
                        f"Response: {mess_obj.value_as_dict}, "
                        f"Message type: {type(mess_obj)}, "
                        f"Message: {getattr(mess_obj, 'message', 'N/A')}"
                    )
                except Exception as e:
                    self._token_refresh_error = e
                    self._token_refresh_event.set()
                    _LOGGER.error(
                        f"Unexpected error processing token refresh: {e}. "
                        f"Response: {getattr(mess_obj, 'value_as_dict', 'N/A')}"
                    )
            # Handle binary file
            elif isinstance(mess_obj, BinaryFile):
                pass

            elif isinstance(mess_obj, Keepalive):
                pass
            else:
                pass

        except LoxoneTokenError:
            raise

        except (LoxoneUnauthorisedError, LoxoneAuthEscalatedError):
            # Hard credential rejection — must reach the ``run()``
            # supervisor (see ``_check_auth_response``). Without this
            # clause the generic handler below would log it away and
            # the connection would keep limping along unauthenticated.
            raise

        except Exception as e:
            _LOGGER.error(f"Error in websocket event handler: {e}", exc_info=True)
