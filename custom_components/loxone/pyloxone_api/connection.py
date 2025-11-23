"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import asyncio
import hashlib
import json
import logging
import time
import urllib
from base64 import b64decode, b64encode
from dataclasses import dataclass
from queue import Queue
from types import TracebackType
from typing import Any, Awaitable, Callable, Dict, List, NoReturn, Optional
from urllib.parse import urlparse

import websockets as wslib
import websockets.exceptions
from async_upnp_client import aiohttp
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import HMAC, SHA1, SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Util import Padding

from .const import (AES_KEY_SIZE, CMD_AUTH_WITH_TOKEN, CMD_ENABLE_UPDATES,
                    CMD_GET_API_KEY, CMD_GET_KEY, CMD_GET_KEY_AND_SALT,
                    CMD_GET_PUBLIC_KEY, CMD_GET_VISUAL_PASSWD, CMD_KEEP_ALIVE,
                    CMD_KEY_EXCHANGE, CMD_REFRESH_TOKEN,
                    CMD_REFRESH_TOKEN_JSON_WEB, CMD_REQUEST_TOKEN,
                    CMD_REQUEST_TOKEN_JSON_WEB, DELAY_CHECK_TOKEN_REFRESH,
                    IV_BYTES, KEEP_ALIVE_PERIOD, LOXAPPPATH, MAX_REFRESH_DELAY,
                    MAX_WEBSOCKET_MESSAGE_SIZE, RECONNECT_DELAY,
                    RECONNECT_TRIES, SALT_BYTES, SALT_MAX_AGE_SECONDS,
                    SALT_MAX_USE_COUNT, TIMEOUT, TOKEN_PERMISSION)
from .exceptions import (LoxoneConnectionClosedOk, LoxoneConnectionError,
                         LoxoneException, LoxoneOutOfServiceException,
                         LoxoneServiceUnAvailableError, LoxoneTokenError)
from .loxone_http_client import LoxoneAsyncHttpClient
from .loxone_token import LoxoneToken, LxJsonKeySalt
from .message import (BaseMessage, BinaryFile, LLResponse, MessageType,
                      TextMessage, parse_message)
from .websocket_protocol import LoxoneClientConnection

_LOGGER = logging.getLogger(__name__)
import warnings

# Filter out the specific warning
warnings.filterwarnings(
    "ignore",
    message="Detected blocking call to load_verify_locations",
    module="httpx._config",
)


def time_elapsed_in_seconds():
    return int(round(time.time()))


@dataclass
class MessageForQueue:
    command: str
    flag: bool


class LoxoneBaseConnection:
    _URL_FORMAT = "ws://{url}/ws/rfc6455"
    _SSL_URL_FORMAT = "wss://{url}/ws/rfc6455"

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        token: Optional[dict] = None,
        port: int = 8080,
        timeout: Optional[float] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.token = token
        self.port = port
        self.timeout = None if timeout == 0 else timeout
        self.connection: wslib.ClientConnection | None = None
        self._recv_loop: Optional[Any] = None
        self._pending_task = []
        self._closed = False

        # Parse the server input to extract scheme if present
        parsed = urlparse(host if "://" in host else f"//{host}", scheme="")
        self.scheme = parsed.scheme or ("https" if port == 443 else "http")
        netloc = parsed.hostname or parsed.path

        # do not use port 80 or 443 if the scheme is http/ws or https/wss
        default_port = 80 if self.scheme == "http" else 443
        used_port = port if port and port != default_port else None

        # Build the full address but without the scheme
        if used_port:
            self.url = f"{netloc}:{used_port}{parsed.path}"
        else:
            self.url = f"{netloc}{parsed.path}"

        # Generate random 16 byte AES initialisation vector (iv)
        self._iv: bytes = get_random_bytes(IV_BYTES)
        # Generate an AES256-CBC key.
        self._aes_key: bytes = get_random_bytes(AES_KEY_SIZE)
        self._public_key: str = ""
        self._session_key: str = ""

        self.miniserver_version: List[int] = []
        self.miniserver_serial: str = ""
        self.structure_file: Dict = {}

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
            self._token = LoxoneToken(
                token=token_str,
                valid_until=valid_until,
                hash_alg=hash_alg,
                key="",
                unsecure_password=unsecure_password,
            )
        else:
            self._token = LoxoneToken()
        self._key: str = ""
        self._user_salt: str = ""
        self._hash_alg: str = ""

        self._salt_has_expired: bool = False
        self._salt_time_stamp: int = 0
        self._visual_hash = None
        self._message_queue: Queue[MessageForQueue] = Queue()
        self._secured_queue = Queue(maxsize=1)
        self.message_header = None

    def get_token_dict(self) -> dict:
        return {
            "token": self._token.token,
            "valid_until": self._token.valid_until,
            "hash_alg": self._token.hash_alg,
            "unsecure_password": self._token.unsecure_password,
        }

    def reset_token(self):
        self._token = LoxoneToken()

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
        _LOGGER.debug(f"Send text command: {command}")
        if encrypted:
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
            await self.connection.send([command])
        except Exception as e:
            _LOGGER.error("Error while sending...")
            raise e

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
        _LOGGER.debug("Generating a new salt")
        self._salt = get_random_bytes(SALT_BYTES).hex()

        self._salt_time_stamp = time_elapsed_in_seconds()
        self._salt_used_count = 0

    def _new_salt_needed(self):
        self._salt_used_count += 1
        if (
            self._salt_used_count > SALT_MAX_USE_COUNT
            or time_elapsed_in_seconds() - self._salt_time_stamp > SALT_MAX_AGE_SECONDS
        ):
            return True
        return False

    async def _refresh_token(self):
        token_hash = self._hash_token()
        if self.miniserver_version < [10, 2]:
            command = f"{CMD_REFRESH_TOKEN}{token_hash}/{self.username}"
        else:
            command = f"{CMD_REFRESH_TOKEN_JSON_WEB}{token_hash}/{self.username}"
        self._message_queue.put(MessageForQueue(command, True))

    def _hash_token(self):
        token_hash_str = f"{self._token.token}"
        if self._hash_alg == "SHA1":
            hash_module = SHA1

        elif self._hash_alg == "SHA256":
            hash_module = SHA256
        else:
            _LOGGER.error(f"Unrecognised hash algorithm: {self._hash_alg}")
            return None

        digester = HMAC.new(
            bytes.fromhex(self._key), token_hash_str.encode("utf-8"), hash_module
        )

        return digester.hexdigest()

    async def _send_secure(self, device_uuid, value, code):
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
            bytes.fromhex(self._visual_hash.key), pwd_hash.encode("utf-8"), hash_module
        )
        new_hash = digester.hexdigest()
        command = "jdev/sps/ios/{}/{}/{}".format(new_hash, device_uuid, value)
        self._message_queue.put(MessageForQueue(command, True))
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

        if not self.connection:
            _LOGGER.debug("No existing connection found. Opening a new connection.")
            self.connection = await self.open()
            # raise exceptions.ConnectionFailure("Connection already exists")
        else:
            _LOGGER.debug("Using existing connection.")

        async def keep_alive() -> NoReturn:
            """Send keep-alive messages to the Miniserver."""
            try:
                while True:
                    await asyncio.sleep(KEEP_ALIVE_PERIOD)
                    await self._send_text_command(CMD_KEEP_ALIVE, encrypted=False)
            except Exception as exc:
                _LOGGER.error(f"Keep-alive task encountered an error: {exc}")
                raise

        async def check_refresh_token() -> NoReturn:
            """Check if the token needs to be refreshed."""
            _LOGGER.debug(f"Start check refresh token task...")
            while True:
                # Calculate 50% of the token lifetime as an integer and limit it to MAX_REFRESH_DELAY
                candidate = int(self._token.seconds_to_expire() * 0.5)

                def generate_refresh_time_log(_seconds_to_refresh: int) -> str:
                    days, remainder = divmod(_seconds_to_refresh, 86400)
                    hours, seconds = divmod(remainder, 3600)
                    minutes, seconds = divmod(seconds, 60)
                    return f"{days}d {hours}h {minutes}m {seconds}s"

                seconds_to_refresh = max(1, min(candidate, MAX_REFRESH_DELAY))
                _LOGGER.debug(
                    f"Seconds to refresh token: {generate_refresh_time_log(seconds_to_refresh)}"
                )

                await asyncio.sleep(seconds_to_refresh)
                command = f"{CMD_GET_KEY}"
                # gets a new key for the token refresh
                old_key = self._key
                try:
                    await self._send_text_command(command, encrypted=False)
                except Exception as exc:
                    _LOGGER.debug(f"Error requesting new key: {exc}")
                    # Wait briefly and then try again to avoid a tight loop in case of errors.
                    await asyncio.sleep(1)
                    continue

                async def _wait_for_key_change(old_key_in: str, timeout: float = 15.0):
                    end = asyncio.get_event_loop().time() + timeout
                    while (
                        self._key == old_key_in
                        and asyncio.get_event_loop().time() < end
                    ):
                        await asyncio.sleep(0.1)

                try:
                    await asyncio.wait_for(_wait_for_key_change(old_key), timeout=15.0)
                except asyncio.TimeoutError:
                    _LOGGER.debug(
                        "Timed out waiting for new key (15s). Will retry on next cycle."
                    )
                else:
                    _LOGGER.debug("Key changed successfully.")
                    await self._refresh_token()

        await self.connection.send(f"{CMD_KEY_EXCHANGE}{self._session_key.decode()}")
        self._recv_loop = asyncio.ensure_future(
            self._do_start_listening(callback, self.connection)
        )

        async def delayed_check_refresh_token():
            await asyncio.sleep(DELAY_CHECK_TOKEN_REFRESH)
            await check_refresh_token()

        # noinspection PyUnreachableCode
        self._pending_task = [
            self._recv_loop,
            asyncio.create_task(self._process_message()),
            asyncio.create_task(keep_alive()),
            asyncio.create_task(delayed_check_refresh_token()),
        ]

        try:
            done, pending = await asyncio.wait(
                self._pending_task, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                try:
                    await task
                except websockets.exceptions.ConnectionClosedOK as e:
                    _LOGGER.debug("Task ConnectionClosedOK received")
                    raise LoxoneConnectionClosedOk(
                        "Connection Closed. Try reconnecting..."
                    )
                    # Cancel pending tasks
                except LoxoneTokenError as e:
                    raise e
                except LoxoneOutOfServiceException as e:
                    _LOGGER.debug(f"Task {task} raised an exception: {e}")
                    raise e
                except websockets.exceptions.ConnectionClosedError as e:
                    _LOGGER.debug(f"Task {task} raised an exception: {e}")
                    raise e
                except websockets.exceptions.ConnectionClosed as e:
                    _LOGGER.debug(f"Task {task} raised an exception: {e}")
                    raise LoxoneConnectionError(
                        "Connection Closed. Try reconnecting..."
                    )
                except Exception as e:
                    _LOGGER.debug(f"Task {task} raised an exception: {e}")
                    raise e
        finally:
            # Cancel pending tasks
            for task in self._pending_task:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._pending_task, return_exceptions=True)

    async def _process_message(self) -> NoReturn:
        while True:
            if not self._message_queue.empty():
                while not self._message_queue.empty():
                    m = self._message_queue.get()
                    await self._send_text_command(m.command, encrypted=m.flag)
            await asyncio.sleep(0.1)

    async def _do_start_listening(
        self,
        callback: Optional[Callable[[Any], Optional[Awaitable[None]]]],
        connection: LoxoneClientConnection,
    ) -> None:
        while True:
            try:
                message = await connection.recv_message()
                await self._websocket_event(message)
                # if  callback and message.message_type == MessageType.TEXT:
                #    print(message)
                if callback and message.message_type in [
                    MessageType.VALUE_STATES,
                    MessageType.TEXT_STATES,
                    MessageType.TEXT,
                    MessageType.KEEPALIVE,
                ]:
                    awaitable = callback(message.as_dict())
                    if awaitable:
                        await awaitable
                else:
                    _LOGGER.debug(
                        f"Message type {list(MessageType)[message.message_type].name} not handled yet ..."
                    )
                    _ = message.as_dict()
                    if _ != {}:
                        _LOGGER.debug(f"Message {message.as_dict()}")

            except Exception as e:
                _LOGGER.error(f"Error in listening loop: {e}")
                raise e

    async def open(
        self, session: aiohttp.ClientSession | None = None
    ) -> Optional[LoxoneClientConnection]:
        # if self.connection:
        #     # someone else already created a new connection
        #     return self.connection

        connector = None
        try:
            connector = LoxoneAsyncHttpClient(
                url=self.url,
                username=self.username,
                password=self.password,
                scheme=self.scheme,
                session=session,
            )

            for attempt in range(RECONNECT_TRIES):
                try:
                    api_resp = await connector.get(CMD_GET_API_KEY)
                    break  # connection successful
                except LoxoneServiceUnAvailableError as e:
                    if attempt < RECONNECT_TRIES - 1:
                        _LOGGER.debug(
                            f"LoxoneServiceUnAvailableError, try again in {RECONNECT_DELAY} seconds..."
                        )
                        await asyncio.sleep(RECONNECT_DELAY)
                    else:
                        _LOGGER.error("Max tries exceeded. Stopping.")
                        raise

            data = await api_resp.content.read()
            _value = LLResponse(data).value
            # The json returned by the miniserver is invalid. It contains " and '.
            # We need to normalise it
            value = json.loads(_value.replace("'", '"'))
            # self.https_status = value.get("httpsStatus")

            self.miniserver_version = (
                [int(x) for x in value.get("version").split(".")]
                if value.get("version")
                else []
            )
            self.miniserver_serial = value.get("snr")
            local = value.get("local", True)
            if not local:
                connector.base_url = str(api_resp.url).replace(CMD_GET_API_KEY, "")
                self.url = connector.base_url.replace("https://", "").replace(
                    "http://", ""
                )

            # Get the structure file
            try:
                lox_app_data = await connector.get(LOXAPPPATH)
            except Exception as e:
                raise e

            status = lox_app_data.status
            if status == 200:
                data = await lox_app_data.content.read()
                self.structure_file = json.loads(data)
                self.structure_file["softwareVersion"] = (
                    self.miniserver_version
                )  # FIXME Legacy use only. Need to fix pyloxone

            # Get the public key
            pk_data = await connector.get(CMD_GET_PUBLIC_KEY)
            pk_data_text = await pk_data.content.read()
            pk = LLResponse(pk_data_text).value
            # Loxone returns a certificate instead of a key, and the certificate is not
            # properly PEM encoded because it does not contain newlines before/after the
            # boundaries. We need to fix both problems. Proper PEM encoding requires 64
            # char line lengths throughout, but Python does not seem to insist on this.
            # If, for some reason, no certificate is returned, _public_key will be an
            # empty string.
            self._public_key = pk.replace(
                "-----BEGIN CERTIFICATE-----", "-----BEGIN PUBLIC KEY-----\n"
            ).replace("-----END CERTIFICATE-----", "\n-----END PUBLIC KEY-----\n")
        finally:
            # Async httpx client must always be closed
            if session is None:
                await connector.session.close()

        # Init RSA cipher
        try:
            # RSA PKCS1 has been broken for a long time. Loxone uses it anyway
            rsa_cipher = PKCS1_v1_5.new(RSA.importKey(self._public_key))
            _LOGGER.debug("init_rsa_cipher successfully...")
        except ValueError as exc:
            _LOGGER.error(f"Error creating RSA cipher: {exc}")
            raise LoxoneException(exc)

        # Generate session key
        aes_key = self._aes_key.hex()
        iv = self._iv.hex()
        session_key = f"{aes_key}:{iv}".encode("utf-8")
        try:
            self._session_key = b64encode(rsa_cipher.encrypt(session_key))
            _LOGGER.debug("generate_session_key successfully...")
        except ValueError as exc:
            _LOGGER.error(f"Error generating session key: {exc}")
            raise LoxoneException(exc) from None

        # generate first salt
        self._generate_salt()

        params = {"url": self.url}
        if self.scheme == "https":
            base_url = self._SSL_URL_FORMAT.format(**params)
        else:
            base_url = self._URL_FORMAT.format(**params)

        self.connection = await wslib.connect(
            base_url,
            open_timeout=TIMEOUT,
            create_connection=LoxoneClientConnection,
            compression=None,
            max_size=MAX_WEBSOCKET_MESSAGE_SIZE,  # 5 megabytes = 5,242,880 bytes
        )

        return self.connection

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._pending_task:
            for task in self._pending_task:
                try:
                    if task and not task.done():
                        task.cancel()
                except Exception:
                    pass
            # Wait for tasks to finish or cancel
            if self._pending_task:
                await asyncio.gather(*self._pending_task, return_exceptions=True)
            # clear pending tasks
            self._pending_task = []

        # Close websocket connection if present
        if self.connection:
            try:
                await self.connection.close()
            except Exception:
                pass
            finally:
                self.connection = None

        _LOGGER.debug("Connection closed.")

    async def send_websocket_command(self, device_uuid: str, value: str):
        """Send a websocket command to the Miniserver."""
        command = "jdev/sps/io/{}/{}".format(device_uuid, value)
        _LOGGER.debug("Call send_websocket_command: {}".format(command))
        self._message_queue.put(MessageForQueue(command=command, flag=True))

    async def send_secured__websocket_command(
        self, device_uuid: str, value: str, code: str
    ):
        command = f"{CMD_GET_VISUAL_PASSWD}{self.username}"
        _LOGGER.debug(f"Call send_secured__websocket_command: {command}")
        self._secured_queue.put(self._send_secure(device_uuid, value, code))
        self._message_queue.put(MessageForQueue(command=command, flag=True))

    async def _websocket_event(self, message: Dict[str, Any] | BaseMessage) -> None:
        """Handle websocket event."""
        mess_obj = None
        if isinstance(message, str) and message.startswith("{"):
            mess_obj = parse_message(message, self.message_header.message_type)
        elif isinstance(message, bytes):
            mess_obj = parse_message(message, self.message_header.message_type)
        elif isinstance(message, BaseMessage):
            mess_obj = message

        if mess_obj is None:
            return

        if hasattr(mess_obj, "control") and mess_obj.control.find("/enc/") > -1:
            mess_obj.control = self._decrypt(mess_obj.control)

        if isinstance(mess_obj, TextMessage) and "keyexchange" in mess_obj.message:
            _LOGGER.debug("Key exchange with miniserver...")
            command = f"{CMD_GET_KEY_AND_SALT}/{self.username}"
            self._message_queue.put(MessageForQueue(command, True))

        elif isinstance(mess_obj, TextMessage) and "getkey2" in mess_obj.message:
            _LOGGER.debug("Got get key2")
            self._key = mess_obj.value_as_dict["key"]
            self._user_salt = mess_obj.value_as_dict["salt"]
            self._hash_alg = mess_obj.value_as_dict.get("hashAlg", None)

            if self._token.seconds_to_expire() > 100:
                _LOGGER.debug("Use old token...")
                token_hash = self._hash_token()
                command = "{}{}/{}".format(
                    CMD_AUTH_WITH_TOKEN, token_hash, self.username
                )
                self._message_queue.put(MessageForQueue(command, True))
            else:
                _LOGGER.debug("Acquire new token...")
                new_hash = self._hash_credentials()
                # Request new Token
                if self.miniserver_version < [10, 2]:
                    command = f"{CMD_REQUEST_TOKEN}/{new_hash}/{self.username}/{TOKEN_PERMISSION}/edfc5f9a-df3f-4cad-9dddcdc42c732b82/pyloxone_api"
                else:
                    command = f"{CMD_REQUEST_TOKEN_JSON_WEB}/{new_hash}/{self.username}/{TOKEN_PERMISSION}/edfc5f9a-df3f-4cad-9dddcdc42c732b82/pyloxone_api"
                self._message_queue.put(MessageForQueue(command, True))

        elif isinstance(mess_obj, TextMessage) and "getkey" in mess_obj.message:
            _LOGGER.debug("Got get getkey")
            self._key = mess_obj.value_as_dict["value"]

        elif isinstance(mess_obj, TextMessage) and "getvisusalt" in mess_obj.message:
            self._key = mess_obj.value_as_dict["value"]
            key_and_salt = LxJsonKeySalt()
            key_and_salt.read_user_salt_response(mess_obj.message)
            key_and_salt.time_elapsed_in_seconds = time_elapsed_in_seconds()
            self._visual_hash = key_and_salt

            while not self._secured_queue.empty():
                awaitable = self._secured_queue.get()
                if awaitable:
                    await awaitable

        elif isinstance(mess_obj, TextMessage) and (
            "gettoken" in mess_obj.message or "getjwt" in mess_obj.message
        ):
            self._token.token = mess_obj.value_as_dict.get("token")
            self._token.valid_until = mess_obj.value_as_dict.get("validUntil")
            self._token.key = mess_obj.value_as_dict.get("key")
            self._token.hash_alg = self._hash_alg
            if "unsecurePass" in mess_obj.value_as_dict:
                self._token.unsecure_password = mess_obj.value_as_dict.get("key")
            self._message_queue.put(MessageForQueue(f"{CMD_ENABLE_UPDATES}", True))

        elif isinstance(mess_obj, TextMessage) and (
            "authwithtoken" in mess_obj.message
        ):
            if mess_obj.code == 401:
                self.reset_token()
                raise LoxoneTokenError("Token not vaild anymore")
            else:
                _LOGGER.debug("Got message authwithtoken")
                # await self._send_text_command(f"{CMD_ENABLE_UPDATES}", encrypted=True)
                self._message_queue.put(MessageForQueue(f"{CMD_ENABLE_UPDATES}", True))

        elif isinstance(mess_obj, TextMessage) and ("refreshjwt" in mess_obj.message or "refresh" in mess_obj.message):
            _LOGGER.debug(f"Got {type(mess_obj)}")
            try:
                self._token.token = mess_obj.value_as_dict["token"]
                self._token.valid_until = mess_obj.value_as_dict["validUntil"]
                if "unsecurePass" in mess_obj.value_as_dict:
                    self._token.unsecure_password = mess_obj.value_as_dict["unsecurePass"]
            except KeyError as e:
                _LOGGER.error(
                    f"Missing key in token refresh response: {e}. "
                    f"Response: {mess_obj.value_as_dict}, "
                    f"Message type: {type(mess_obj)}, "
                    f"Message: {getattr(mess_obj, 'message', 'N/A')}"
                )
            except Exception as e:
                _LOGGER.error(
                    f"Unexpected error processing token refresh: {e}. "
                    f"Response: {mess_obj.value_as_dict}"
                )

        elif isinstance(mess_obj, BinaryFile):
            _LOGGER.debug(f"Got {type(mess_obj)}")

        else:
            _LOGGER.debug(f"Got {type(mess_obj)}")
