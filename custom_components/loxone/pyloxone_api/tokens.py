"""A mixin containing token related methods."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import hashlib
import json
import logging
import os
import types
import uuid
from dataclasses import asdict, dataclass
from typing import Final, NoReturn

from Crypto.Hash import HMAC, SHA1, SHA256

from .const import PERMISSION, CMD_GET_KEY2, DEFAULT_TOKEN_PERSIST_NAME, CMD_GET_KEY
from .loxone_exceptions import LoxoneException
from .loxone_types import MiniserverProtocol
from .message import LoxoneResponse

_LOGGER = logging.getLogger(__name__)
# Loxone epoch is 1.1.2009
LOXONE_EPOCH: Final = datetime.datetime(2009, 1, 1, 0, 0)


@dataclass
class LoxoneToken:
    """The LoxoneToken class, used for storing token information"""

    token: str = ""
    valid_until: float = 0  # seconds since 1.1.2009
    key: str = ""
    hash_alg: str = ""
    unsecure_password: bool | None = None

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

    def from_dict(self, token: dict):
        print("D")

    def to_dict(self) -> dict:
        _ = {
            "token": self.token,
            "valid_until": self.valid_until,
            "hash_alg": self.hash_alg,
        }
        return _


class TokensMixin(MiniserverProtocol):
    """Methods relating to tokens.

    Do not instantiate this. It is intended only to be mixed in to the Miniserver class.
    """

    async def _use_token(self) -> None:
        _LOGGER.debug("Try to use stored token.")
        cmd = f"{CMD_GET_KEY}"
        await self._send_text_command(cmd, encrypted=True)

        # token_hash = self._hash_token(message.value)
        # cmd = f"authwithtoken/{token_hash}/{self._user}"
        # message = await self._send_text_command(cmd, encrypted=True)
        #
        # if "unsecurePass" in message.value_as_dict:
        #     self._token.unsecure_password = message.value_as_dict["unsecurePass"]
        #
        # _LOGGER.debug("Loaded token is valid and will be used.")

    async def _acquire_token(self) -> None:
        """Acquire a new authentication token from the token store (if any), or
        from the Miniserver"""
        _LOGGER.debug("Acquiring token from miniserver")
        command = f"{CMD_GET_KEY2}/{self._user}"
        # There is no need for this to be encrypted, if TLS is used, but the docs suggest
        # it should be
        await self._send_text_command(command, encrypted=True)

        # self._key = message.value_as_dict["key"]
        # self._user_salt = message.value_as_dict["salt"]
        # self._hash_alg = message.value_as_dict.get("hashAlg", None)
        # new_hash = self._hash_credentials()
        # # Request a JSON web token. uuid uniquely identifies the client to the
        # # Miniserver, and allows it to look up all the client's tokens.
        # UUID = uuid.UUID(int=uuid.getnode())
        #
        # command = (
        #     f"jdev/sys/getjwt/{new_hash}/{self._user}/{PERMISSION}/{UUID}/pyloxone_api"
        # )
        # # According to the docs, this request MUST be encrypted, though in fact
        # # it doesn’t
        # message = await self._send_text_command(command, encrypted=True)
        # response = LoxoneResponse(message.message)
        # self._token.token = response.value_as_dict["token"]
        # self._token.valid_until = response.value_as_dict["validUntil"]
        # self._token.key = response.value_as_dict["key"]
        # self._token.hash_alg = self._hash_alg
        #
        # if "unsecurePass" in response.value_as_dict:
        #     self._token.unsecure_password = response.value_as_dict["unsecurePass"]

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
            lifetime = self._token.seconds_to_expire()
            await asyncio.sleep(lifetime * 0.8)  # Renew after 80% lifetime, to be safe
            command = f"jdev/sys/refreshjwt/{self._token.token}/{self._user}"
            message = await self._send_text_command(command, encrypted=False)
            _LOGGER.debug("Refreshing token")
            self._token.token = message.value_as_dict["token"]
            self._token.valid_until = message.value_as_dict["validUntil"]
            if "unsecurePass" in message.value_as_dict:
                self._token.unsecure_password = message.value_as_dict["unsecurePass"]

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

    def _hash_token(self, key=None) -> str:
        if key is None:
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

    def _load_from_path(self, token_path: str) -> LoxoneToken:
        persist_token = os.path.join(token_path, DEFAULT_TOKEN_PERSIST_NAME)
        if os.path.exists(persist_token):
            with open(persist_token, "r") as f:
                try:
                    dict_token = json.load(f)
                    _LOGGER.debug("Loading token successfully...")
                    loxone_token = LoxoneToken.from_dict(dict_token)

                    return loxone_token
                except ValueError:
                    return LoxoneToken()
        return LoxoneToken()

    def _safe_to_path(self, token_path: str) -> None:
        persist_token = os.path.join(token_path, DEFAULT_TOKEN_PERSIST_NAME)
        try:
            with open(persist_token, "w") as write_file:
                json.dump(self._token.to_dict(), write_file)
            _LOGGER.debug("Token saved successfully...")

        except IOError:
            _LOGGER.debug("Error while saving token...")
            _LOGGER.debug(f"Tokenpath: {persist_token}")


