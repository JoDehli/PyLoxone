"""
Loxone Api

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""
# TODO: assess which exceptions can be recovered from

from __future__ import annotations

import asyncio
import hashlib
import logging
import types
import dataclasses
import binascii
import urllib.parse
from base64 import b64decode, b64encode
from typing import Any, Coroutine, Iterable, NoReturn, TextIO

from aiohttp import ClientSession, ClientWebSocketResponse
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA1, SHA256
from Crypto.Util import Padding

from .connector import ConnectorMixin
from .exceptions import LoxoneCommandError, LoxoneException
from .message import (
    BaseMessage,
    MessageType,
    TextMessage,
    parse_header,
    parse_message,
)
from .tokens import LoxoneToken, TokensMixin

_LOGGER = logging.getLogger(__name__)


class Miniserver(ConnectorMixin, TokensMixin):
    def __init__(
        self,
        host: str = "",
        port: int = 80,
        user: str = "",
        password: str = "",
        token_store: dict | None = None,
        visual_password: str = "",
        use_tls: bool = False,
    ):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._visual_password = visual_password or password  # Default to password

        if token_store:
            token = token_store.get("token", "")
            valid_until = token_store.get("valid_until", 0)
            key = token_store.get("key", "")
            hash_alg = token_store.get("hash_alg", "")
            self._token = LoxoneToken(token=token, valid_until=valid_until, key=key, hash_alg=hash_alg)
            self.has_token = True
            self._hash_alg = hash_alg
            if self._token.seconds_to_expire() < 3600:
                self.has_token = False
                self._token = LoxoneToken()
        else:
            self.has_token = False
            self._token = LoxoneToken()

        self._use_tls = use_tls
        # If use_tls is True, certificate hostnames will be checked. This means
        # that an IP address cannot be used as a hostname. Set
        # _tls_check_hostname to false to disable this check. This creates a
        # SECURITY RISK.
        self._aes_key: bytes = b""
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._iv: bytes = b""
        self._http_base_url: str = ""
        self._http_session: ClientSession | None = None  # type: ignore
        self._https_status: int = 0  # 0 = no TLS, 1 = TLS available, 2 = cert expired
        self._key: str = ""
        self._local: bool = False
        self._message_queue: list[BaseMessage] = []
        self._message_listeners: list[
            tuple[asyncio.Future[Any], Iterable[MessageType], str]
        ] = []

        self._msInfo: tuple  # type: ignore
        self._public_key = ""
        self._salt_has_expired: bool = False
        self._salt: str = ""
        self._snr: str = ""
        self._structure: dict[str, Any] = {}
        self._tls_check_hostname: bool = True
        self._user_salt: str = ""
        self._ws: ClientWebSocketResponse
        self._version: str = ""

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def user(self) -> str:
        return self._user

    @property
    def password(self) -> str:
        return self._password

    @property
    def msInfo(self) -> tuple:  # type: ignore
        return self._msInfo

    @property
    def snr(self) -> str:
        return self._snr

    @property
    def structure(self) -> dict[Any, Any]:
        return self._structure

    @property
    def visual_password(self) -> str:
        return self._visual_password

    @visual_password.setter
    def visual_password(self, visual_password):
        self._visual_password = visual_password

    @property
    def token_dict(self) -> dict:
        return dataclasses.asdict(self._token, dict_factory=dict)

    @property
    def version(self) -> list[int]:
        """The Miniserver software version, as a list of ints eg [12,0,1,2]"""
        return [int(x) for x in self._version.split(".")] if self._version else []

    # ---------------------------------------------------------------------------- #
    #                                Public methods                                #
    # ---------------------------------------------------------------------------- #

    async def connect(self) -> None:
        """Open an authenticated websocket connection to the Miniserver.

        Retry several times, with backoff, if necessary.
        """
        await self._ensure_reachable()
        await self._get_public_key_and_structure_file()
        await self._open_websocket()
        # Run message listeners first, or we wont get any messages
        self._run_in_background(self._receive_and_add_to_queue())
        self._run_in_background(self._process_message())
        await self._generate_and_pass_key()
        self._generate_salt()

        if self.has_token:
            try:
                await self._use_token()
            except LoxoneCommandError as exp:
                if exp.code == 401:
                    _LOGGER.debug("Token is invalid or expired! Try to reconnect and aquire new token.")
                    self.has_token = False
                    self._token = LoxoneToken()
                    await self.close()
                    await self.connect()
        else:
            await self._acquire_token()

        self._run_in_background(self._update_salt())
        self._run_in_background(self._keep_alive())
        self._run_in_background(self._refresh_token())

    async def close(self) -> None:
        """Close the connection to the miniserver, and gracefully shutdown."""
        _LOGGER.debug("Stopping tasks, and closing connection")
        # We should probably kill the token, but this causes the websocket to
        # close immediately, so will need special handling
        # await self._kill_token()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks = []
        await self._ws.close()
        await self._ws_session.close()
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

    async def enable_state_updates(self) -> None:
        """Tell the Miniserver to start sending binary update messages."""
        command = "jdev/sps/enablebinstatusupdate"
        # Gen 1 miniserver may require encryption here
        _ = await self._send_text_command(command)

    async def get_state_updates(self) -> BaseMessage:
        """Wait for and then return a state update from the Miniserver."""
        return await self._get_message(
            [
                MessageType.VALUE_STATES,
                MessageType.TEXT_STATES,
                MessageType.DAYTIMER_STATES,
                MessageType.WEATHER_STATES,
            ]
        )

    async def send_control_command(self, uuid: str, command: str) -> TextMessage:
        """Send a command to a Miniserver control."""
        cmd = f"jdev/sps/io/{uuid}/{command}"
        _LOGGER.debug(f"Send control command: {cmd}")
        return await self._send_text_command(cmd)

    async def send_secured_control_command(
        self, uuid: str, command: str
    ) -> TextMessage:
        """Send a secured command to a Miniserver control."""

        # TODO: Refactor with tokens._hash_credentials and _hash_token
        hash_module: types.ModuleType

        cmd = f"jdev/sys/getvisusalt/{self._user}"
        message = await self._send_text_command(cmd, encrypted=True)

        visual_key = message.value_as_dict["key"]
        visual_salt = message.value_as_dict["salt"]
        visual_hash_alg = message.value_as_dict.get("hashAlg", None)

        if visual_hash_alg == "SHA1":
            algorithm = hashlib.sha1()
            hash_module = SHA1
        elif visual_hash_alg == "SHA256":
            algorithm = hashlib.sha256()
            hash_module = SHA256
        else:
            _LOGGER.error(f"Unrecognised hash algorithm: {visual_hash_alg}")
            raise LoxoneException(f"Unrecognised hash algorithm: {visual_hash_alg}")
        algorithm.update(f"{self._visual_password}:{visual_salt}".encode("utf-8"))
        pw_hash = algorithm.hexdigest().upper()
        # pw_hash = f"{self._user}:{pw_hash}".encode("utf-8")
        digester = HMAC.new(
            bytes.fromhex(visual_key),
            f"{pw_hash}".encode("utf-8"),
            digestmod=hash_module,
        )
        visual_hash = digester.hexdigest()
        cmd = f"jdev/sps/ios/{visual_hash}/{uuid}/{command}"
        _LOGGER.debug(f"Send secured control command: {cmd}")
        return await self._send_text_command(cmd)

    # ---------------------------------------------------------------------------- #
    #                                Private methods                               #
    # ---------------------------------------------------------------------------- #

    def _run_in_background(
        self, task: Coroutine[Any, Any, NoReturn]
    ) -> asyncio.Task[Any]:
        """Run a coroutine as a background task.

        The task will run forever, until it is cancelled, or the event loop
        terminates. If an exception occurs, it will be raised in the main task."""

        def handle_errors(task: asyncio.Task[Any]) -> None:
            try:
                """Raise any errors generated by a background task"""
                # Fetching the result of a task will cause any exceptions which
                # have occurred to be raised
                _ = task.result()
            except asyncio.CancelledError:
                _LOGGER.debug(f"Cancellling {task.get_name()}")
            except asyncio.InvalidStateError:
                _LOGGER.debug(f"InvalidStateError {task.get_name()}")
            # except Exception:
            #     raise

        _task = asyncio.create_task(task, name=task.__name__)
        # If an exception occurs in a task, it is considered done, so we add a
        # callback which can re-raise any exceptions in the context of the main
        # co-routine
        _task.add_done_callback(handle_errors)
        self._background_tasks.append(_task)
        return _task

    async def _send_text_command(
        self, command: str = "", encrypted: bool = False
    ) -> TextMessage:
        """Send a (text) command to the Miniserver, and return the response.

        If encrypted=True, the message will be encrypted, and will be sent using
        Loxone's 'jdev/sys/enc' command. We do not handle 'jdev/sys/fenc'
        full encryption, which encrypts the response as well.

        Miniserver gen 2 uses TLS, so most commands do not need encrypting. But
        some commands (to do with tokens) still seem to need it.

        """

        expected_control = command
        if encrypted:
            if self._salt_has_expired:
                old_salt = self._salt
                self._generate_salt()
                # The miniserver needs the text terminated with a zero byte,
                # though this is not documented
                command_string = f"nextsalt/{old_salt}/{self._salt}/{command}\x00"
            else:
                command_string = f"salt/{self._salt}/{command}\x00"
            padded_bytes = Padding.pad(bytes(command_string, "utf-8"), 16)
            aes_cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
            cipher = b64encode(aes_cipher.encrypt(padded_bytes))
            enc_cipher = urllib.parse.quote(cipher.decode())
            command = f"jdev/sys/enc/{enc_cipher}"

        await self._ws.send_str(command)
        # According to the API docs, "The Miniserver will answer every command
        # it receives, it will return a TextMessage as confirmation." The
        # returned message will have a control attribute which should be the
        # same as the command.
        message = await self._get_message([MessageType.TEXT], expected_control)
        assert isinstance(message, TextMessage)
        # Sometimes the miniserver responds with "/dev ..." in the control,
        # even though the command was "/jdev ...". We need to check for both.
        if message.control not in [expected_control, expected_control[1:]]:
            raise LoxoneException(
                f"Expected {expected_control}, but received {message.control}"
            )
        if message.code != 200:
            raise LoxoneCommandError(code=message.code, message=message.value)
        return message

    async def _get_message(
        self, message_types: Iterable[MessageType], expected_control: str = ""
    ) -> BaseMessage:
        """Get a message whose type is in message_types, from the queue.

        If message_types = [MessageType.TEXT] then expected_control may be set,
        and only messages with that control will be returned."""

        # Sanity check
        if expected_control != "" and message_types != [MessageType.TEXT]:
            raise ValueError("Illegal parameters to _get_message")
        # Create a future and add to a list. The future's result will be set by
        # the _process_message method, when a relevant message is found.
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        listener = (future, message_types, expected_control)
        self._message_listeners.append(listener)
        _LOGGER.debug(
            f"About to wait for {message_types} with expected_control = {expected_control}"
        )
        result: BaseMessage = await future
        _LOGGER.debug(f"returning from wait for {message_types} with {result}")
        return result

    def _decrypt(self, command: str) -> bytes:
        """AES decrypt a command returned by the miniserver."""
        # This is old code. Do we need it? It probably doesn't work!

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

    async def _restart(self) -> None:
        """Close and re-open the connection, following a Miniserver reboot."""

        async def _do_restart() -> None:
            await asyncio.sleep(10)  # Maybe we do not need this. But for safety we leave it for now.
            await self.connect()
            await self.enable_state_updates()

        _LOGGER.debug("Reconnecting")
        asyncio.create_task(_do_restart())
        await self.close()

    # ---------------------------------------------------------------------------- #
    #                               Background tasks                               #
    # ---------------------------------------------------------------------------- #

    async def _update_salt(self) -> NoReturn:
        "Every hour, require the salt to be updated."
        while True:
            await asyncio.sleep(3600)
            # Set a flag, so that the salt will be updated next time an
            # encrypted command is sent
            _LOGGER.debug("Salt has expired")
            self._salt_has_expired = True

    async def _keep_alive(self) -> NoReturn:
        """Send a keep-alive message to the Miniserver every 4.5 minutes."""
        # The miniserver will close the connection if it doesn’t receive a
        # message for 5 minutes. Keepalive messages are sent to keep the
        # connection open. NB These are different from the Keepalive ping pong
        # that websockets use.
        while True:
            await asyncio.sleep(270)  # 270 seconds = 4.5 minutes
            await self._ws.send_str("keepalive")
            await self._get_message([MessageType.KEEPALIVE])

    async def _receive_and_add_to_queue(self) -> NoReturn:
        """Listen to all messages from the Miniserver, and add them to a queue.

        The queue will be processed later.
        """
        # The Loxone API docs say:
        #
        # > As mentioned in the chapter on how to setup a connection, messages
        # > sent by the Miniserver are always prequeled by a binary message that
        # > contains a MessageHeader. So at first you’ll receive the binary
        # > Message-Header and then the payload follows in a separate message.
        #
        # But this is not quite right because the docs also say, for an
        # out-of-service indicator:
        #
        # > No message is going to follow this header, the Miniserver closes the
        # > connection afterwards, the client may try to reconnect.
        #
        # And:
        #
        # > An Estimated-Header is always followed by an exact Header to be able
        # > to read the data correctly!
        #
        # And:
        #
        # a keepalive header is sent by itself. No message body follows it.

        while True:
            header_data = await self._ws.receive_bytes()
            if not isinstance(header_data, bytes):
                raise LoxoneException(
                    f"Expected a bytes header, but received {header_data}"
                )
            _LOGGER.debug(f"Parsing header {header_data[:80]!r}")
            header = parse_header(header_data)
            if header.message_type is MessageType.OUT_OF_SERVICE:
                # raise LoxoneOutOfServiceException("Miniserver is out of service")
                _LOGGER.debug("Miniserver out of service.")
                await self._restart()

            # Now get the message body. NB this assumes that the body
            # immediately follows the header. KEEPALIVE headers are not followed
            # by a body, so there is no body to wait for!
            if header.message_type is MessageType.KEEPALIVE:
                message_data: str | bytes = ""
            else:
                ws_msg = await self._ws.receive()
                message_data = ws_msg.data

            _LOGGER.debug(
                f"Parsing message {message_data[:80]!r} ({header.message_type})"
            )
            message = parse_message(message_data, header.message_type)
            self._message_queue.append(message)
            _LOGGER.debug(f"Current state of queue is {self._message_queue}")

    async def _process_message(self) -> NoReturn:
        """Process messages in the queue and send them to awaiting coroutines."""
        while True:
            # Find all listeners waiting for a message which is in the queue.
            # This is very inefficient, but it works for now
            for message in self._message_queue:
                for listener in self._message_listeners:
                    (future, message_types, expected_control) = listener
                    if (
                        isinstance(message, TextMessage)
                        and message_types == [MessageType.TEXT]
                        and expected_control
                    ):
                        if message.control in [expected_control, expected_control[1:]]:
                            self._message_listeners.remove(listener)
                            self._message_queue.remove(message)
                            future.set_result(message)
                            break
                        break
                    elif message.message_type in message_types:
                        self._message_listeners.remove(listener)
                        self._message_queue.remove(message)
                        future.set_result(message)
                        break
            await asyncio.sleep(0)

    # ---------------------------------------------------------------------------- #
    #                         Context manager magic methods                        #
    # ---------------------------------------------------------------------------- #

    async def __aenter__(self) -> Miniserver:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        await self.close()
        return False
