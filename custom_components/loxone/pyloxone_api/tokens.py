"""A mixin containing token related methods."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import types
import uuid
from dataclasses import dataclass
from typing import Final, NoReturn

from Crypto.Hash import HMAC, SHA1, SHA256

from .exceptions import LoxoneException
from .message import LoxoneResponse
from .loxone_types import MiniserverProtocol

_LOGGER = logging.getLogger(__name__)
# Loxone epoch is 1.1.2009
LOXONE_EPOCH: Final = datetime.datetime(2009, 1, 1, 0, 0)


@dataclass
class LoxoneToken:
    """The LoxoneToken class, used for storing token information"""

    token: str = ""
    valid_until: float = 0  # seconds since 1.1.2009
    key: str = ""

    def seconds_to_expire(self) -> int:
        """The number of seconds until this token expires."""

        # current number of seconds since epoch
        current_seconds_since_epoch = (
            datetime.datetime.now() - LOXONE_EPOCH
        ).total_seconds()
        # work out how many seconds are left
        if self.valid_until == 0:
            raise ValueError("Cannot have valid_until == 0")
        return int(self.valid_until - current_seconds_since_epoch)


class TokensMixin(MiniserverProtocol):
    """Methods relating to tokens.

    Do not instantiate this. It is intended only to be mixed in to the Miniserver class."""

    async def _acquire_token(self) -> None:
        """Acquire a new authentication token from the Miniserver"""
        _LOGGER.debug("Acquiring token from miniserver")
        command = f"jdev/sys/getkey2/{self._user}"
        # There is no need for this to be encrypted, if TLS is used, but the docs suggest
        # it should be
        message = await self._send_text_command(command, encrypted=True)

        self._key = message.value_as_dict["key"]
        self._user_salt = message.value_as_dict["salt"]
        self._hash_alg = message.value_as_dict.get("hashAlg", None)
        new_hash = self._hash_credentials()
        # Request a JSON web token. uuid uniquely identifies the client to the
        # Miniserver, and allows it to look up all the client's tokens.
        UUID = uuid.UUID(int=uuid.getnode())
        # PERMISSION can be 2 for for a 'short' lifespan token (days), or 4 for
        # a longer lifespan (weeks). We ask for shorter token here. Renewing it
        # is relatively easy, and the lifespan ensures that the tokens don't
        # stick around for too long in the miniserver's memory if we have
        # frequent restarts.
        PERMISSION = 2
        command = (
            f"jdev/sys/getjwt/{new_hash}/{self._user}/{PERMISSION}/{UUID}/pyloxone_api"
        )
        # According to the docs, this request MUST be encrypted, though in fact
        # it doesn’t
        message = await self._send_text_command(command, encrypted=True)
        response = LoxoneResponse(message.message)
        self._token.token = response.value_as_dict["token"]
        self._token.valid_until = response.value_as_dict["validUntil"]
        self._token.key = response.value_as_dict["key"]

    async def _kill_token(self) -> None:
        """Remove the token from the Miniserver's storage.

        This will cause the websocket connection to close immediately"""
        _LOGGER.debug("Killing token")
        # ToThis command requires Loxone >= 11.2. Before then, the token had to be hashed
        command = f"jdev/sys/killtoken/{self._token.token}/{self._user}"
        await self._send_text_command(command)

    async def _refresh_token(self) -> NoReturn:
        """A background task which refreshes the token periodically.

        Do not call this directly - it will never return!"""
        # Token does not need to be hashed for Loxone >=11.2
        # token_hash = await self._hash_token()
        while True:
            command = f"jdev/sys/refreshjwt/{self._token.token}/{self._user}"
            message = await self._send_text_command(command, encrypted=False)
            _LOGGER.debug("Refreshing token")
            self._token.token = message.value_as_dict["token"]
            self._token.valid_until = message.value_as_dict["validUntil"]
            lifetime = self._token.seconds_to_expire()
            await asyncio.sleep(lifetime * 0.8)  # Renew after 80% lifetime, to be safe

    async def _check_token(self) -> None:
        """Check whether a token is still valid, without renewing it"""
        # Token does not need to be hashed for Loxone >=11.2
        # token_hash = await self._hash_token()
        command = f"jdev/sys/checktoken/{self._hash_token()}/{self._user}"
        await self._send_text_command(command, encrypted=True)
        _LOGGER.debug(f"Token is verified for {self._user}.")

    def _hash_credentials(self) -> str:
        hash_module: types.ModuleType

        if self._hash_alg == "SHA1":
            algorithm = hashlib.sha1()
            hash_module = SHA1
        elif self._hash_alg == "SHA256":
            algorithm = hashlib.sha256()
            hash_module = SHA256
        else:
            _LOGGER.error(f"Unrecognised hash algorithm: {self._hash_alg}")
            raise LoxoneException(f"Unrecognised hash algorithm: {self._hash_alg}")
        algorithm.update(f"{self._password}:{self._user_salt}".encode("utf-8"))
        pw_hash = algorithm.hexdigest().upper()
        # pw_hash = f"{self._user}:{pw_hash}".encode("utf-8")
        digester = HMAC.new(
            bytes.fromhex(self._key),
            f"{self._user}:{pw_hash}".encode("utf-8"),
            digestmod=hash_module,
        )
        return digester.hexdigest()

    def _hash_token(self) -> str:
        key = self._token.key
        if self._hash_alg == "SHA1":
            digester = HMAC.new(
                bytes.fromhex(key),
                self._token.token.encode("utf-8"),
                SHA1,
            )
        elif self._hash_alg == "SHA256":
            digester = HMAC.new(
                bytes.fromhex(key),
                self._token.token.encode("utf-8"),
                SHA256,
            )
        else:
            _LOGGER.error(f"Unrecognised hash algorithm: {self._hash_alg}")
            raise LoxoneException(f"Unrecognised hash algorithm: {self._hash_alg}")
        return digester.hexdigest()
