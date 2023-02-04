"""Various types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TextIO

from async_upnp_client import aiohttp

from .message import TextMessage

if TYPE_CHECKING:
    from .tokens import LoxoneToken


class MiniserverProtocol(Protocol):
    """Protocol, used only for type checking the mixins.

    These attributes and methods must have the same types as those in the main
    Miniserver class"""

    _host: str
    _password: str
    _port: int
    _tls_check_hostname: bool
    _token_store: dict| None
    _http_base_url: str
    _http_session: aiohttp.ClientSession | None
    if TYPE_CHECKING:
        _token: LoxoneToken
    _use_tls: bool
    _user: str
    _https_status: int

    async def _send_text_command(
        self, command: str = "", encrypted: bool = False
    ) -> TextMessage:
        ...

    def _hash_token(self) -> str:
        ...
