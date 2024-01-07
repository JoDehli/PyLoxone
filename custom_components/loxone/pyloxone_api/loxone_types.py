"""Various types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

# import httpx
from websockets.legacy.client import WebSocketClientProtocol

from .loxone_http_client import LoxoneAsyncHttpClient
from .message import MessageHeader, TextMessage

if TYPE_CHECKING:
    from tokens import LoxoneToken


class MiniserverProtocol(Protocol):
    _host: str
    _port: int
    _user: str
    _password: str
    _use_tls: bool
    _url: str

    if TYPE_CHECKING:
        _token: LoxoneToken
    _http_client: LoxoneAsyncHttpClient | None
    _tls_check_hostname: bool
    _https_status: int
    _version: str
    _snr: str
    _local: bool
    _ws: WebSocketClientProtocol | None = None
    _ping_timeout: int
    _aes_key: bytes
    message_header: MessageHeader | None

    _key: str = ""
    _hash_alg: str = ""

    _salt: str = ""
    _salt_has_expired: bool = False
    _user_salt: str = ""
    _token_path: str = ""

    def websocket_is_open(self) -> bool:
        ...

    async def send_ws(self, command: str = ""):
        ...

    async def _send_text_command(
        self, command: str = "", encrypted: bool = False
    ) -> TextMessage:
        ...

    async def _open_web_socket_connection(self):
        ...

    async def on_message(self, message) -> None:
        ...

    async def on_error(self, error) -> None:
        ...

    async def on_close(self) -> None:
        ...

    # Message Handler methods
    async def handle_message(self, message) -> None:
        ...

    # Token methods
    def _hash_token(self) -> str:
        ...

    async def _acquire_token(self) -> None:
        ...

    def _generate_salt(self) -> None:
        ...

    def _hash_credentials(self) -> str:
        ...

    def _load_from_path(self, token_path: str) -> LoxoneToken:
        ...

    def _safe_to_path(self, token_path: str) -> None:
        ...
