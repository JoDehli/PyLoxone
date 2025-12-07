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
from dataclasses import dataclass, field
from types import TracebackType
from typing import (Any, Awaitable, Callable, Dict, List, NoReturn, Optional,
                    Union)
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
from .message import (BaseMessage, BinaryFile, Keepalive, LLResponse,
                      MessageType, TextMessage, parse_message)
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
        self._key_update_event: Optional[asyncio.Event] = None
        self._shutdown_event = asyncio.Event()

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
        self._session_key: str = ""

        self.miniserver_version: List[int] = []
        self.miniserver_serial: str = ""
        self.structure_file: Dict = {}

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
        self._visual_hash = None
        # Replace synchronous Queue with asyncio.Queue with bounded size
        self._message_queue: asyncio.Queue[MessageForQueue] = asyncio.Queue(
            maxsize=1000
        )
        self._secured_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self.message_header = None

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
                command = f"{CMD_REFRESH_TOKEN}{token_hash}/{self.username}"
            else:
                command = f"{CMD_REFRESH_TOKEN_JSON_WEB}{token_hash}/{self.username}"

            try:
                # Use put() with timeout for critical internal messages
                await asyncio.wait_for(
                    self._message_queue.put(MessageForQueue(command, True)), timeout=5.0
                )
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout adding refresh token command to queue")
                raise
        except Exception as e:
            _LOGGER.error(f"Token refresh failed: {e}")
            raise

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
        # Ensure value is string when formatting command
        command = "jdev/sps/ios/{}/{}/{}".format(new_hash, device_uuid, str(value))
        # Fix: Use await with put() and timeout for critical secure commands
        try:
            await asyncio.wait_for(
                self._message_queue.put(MessageForQueue(command, True)), timeout=2.0
            )
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

        # Clear shutdown event when starting
        self._shutdown_event.clear()

        async def keep_alive() -> NoReturn:
            """Send keep-alive messages to the Miniserver."""
            try:
                while True:
                    await asyncio.sleep(KEEP_ALIVE_PERIOD)
                    try:
                        await self._send_text_command(CMD_KEEP_ALIVE, encrypted=False)
                    except Exception as exc:
                        _LOGGER.error(f"Keep-alive message failed: {exc}")
                        raise
            except asyncio.CancelledError:
                _LOGGER.debug("Keep-alive task cancelled")
                raise
            except Exception as exc:
                _LOGGER.error(f"Keep-alive task encountered an error: {exc}")
                raise

        async def check_refresh_token() -> NoReturn:
            """Check if the token needs to be refreshed."""
            _LOGGER.debug(f"Start check refresh token task...")
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
                        _LOGGER.debug(
                            f"Seconds to refresh token: {generate_refresh_time_log(seconds_to_refresh)}"
                        )

                        await asyncio.sleep(seconds_to_refresh)

                        # Check shutdown before proceeding
                        if self._shutdown_event.is_set():
                            break

                        command = f"{CMD_GET_KEY}"
                        # gets a new key for the token refresh
                        # Store old key and create event to wait for update
                        old_key = self._key
                        key_updated_event = asyncio.Event()
                        self._key_update_event = (
                            key_updated_event  # Store for _websocket_event to signal
                        )

                        try:
                            await self._send_text_command(command, encrypted=False)
                        except Exception as exc:
                            _LOGGER.error(f"Error requesting new key: {exc}")
                            self._key_update_event = None
                            await asyncio.sleep(1)
                            continue

                        try:
                            await asyncio.wait_for(
                                key_updated_event.wait(), timeout=15.0
                            )
                            # Verify key actually changed
                            if self._key == old_key:
                                _LOGGER.warning(
                                    "Key was not updated despite event being set"
                                )
                                continue
                            else:
                                _LOGGER.debug("Key changed successfully.")
                                await self._refresh_token()

                        except asyncio.TimeoutError:
                            _LOGGER.warning(
                                "Timed out waiting for new key (15s). Will retry on next cycle."
                            )
                        finally:
                            self._key_update_event = None

                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        _LOGGER.error(f"Error in token refresh cycle: {e}")
                        await asyncio.sleep(1)  # Avoid tight loop on errors

            except asyncio.CancelledError:
                _LOGGER.debug("Token refresh task cancelled")
                raise
            except Exception as exc:
                _LOGGER.error(f"Token refresh task failed: {exc}")
                raise

        try:
            if not self._session_key:
                raise RuntimeError("Session key not initialized")

            await self.connection.send(
                f"{CMD_KEY_EXCHANGE}{self._session_key.decode()}"
            )
        except Exception as e:
            _LOGGER.error(f"Failed to send key exchange: {e}")
            raise

        self._recv_loop = asyncio.ensure_future(
            self._do_start_listening(callback, self.connection)
        )

        async def delayed_check_refresh_token():
            try:
                await asyncio.sleep(DELAY_CHECK_TOKEN_REFRESH)
                await check_refresh_token()
            except asyncio.CancelledError:
                _LOGGER.debug("Delayed token refresh task cancelled")
                raise
            except Exception as e:
                _LOGGER.error(f"Delayed token refresh failed: {e}")
                raise

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
                    raise LoxoneConnectionClosedOk
                except LoxoneTokenError as e:
                    _LOGGER.error(f"Token error {e}")
                    raise
                except LoxoneOutOfServiceException as e:
                    _LOGGER.error(f"Miniserver out of service: {e}")
                    raise
                except websockets.exceptions.ConnectionClosedError as e:
                    _LOGGER.error(f"Connection closed with error: {e}")
                    raise LoxoneConnectionError
                except websockets.exceptions.ConnectionClosed as e:
                    _LOGGER.error(
                        "Connection closed by websocket, converting to LoxoneConnectionError"
                    )
                    raise LoxoneConnectionError("Connection closed") from None
                except asyncio.CancelledError:
                    pass
                    # Don't raise, this is expected during shutdown
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
        except Exception as e:
            raise
        finally:
            # Cancel pending tasks
            for task in self._pending_task:
                if task and not task.done():
                    task.cancel()

            if self._pending_task:
                await asyncio.gather(*self._pending_task, return_exceptions=True)

    async def _process_message(self) -> NoReturn:
        """Process queued messages with graceful shutdown."""
        _LOGGER.debug("Message processing task started")

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Use asyncio.Queue.get() with timeout
                    msg = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=0.5,  # Check shutdown event regularly
                    )
                    # Log queue depth periodically for monitoring
                    queue_size = self._message_queue.qsize()
                    if queue_size > 100:
                        _LOGGER.warning(f"Message queue depth: {queue_size}")
                    elif queue_size > 0:
                        _LOGGER.debug(f"Message queue depth: {queue_size}")

                    try:
                        await self._send_text_command(msg.command, encrypted=msg.flag)
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
        try:
            while True:
                try:
                    if not connection or connection.state == connection.state.CLOSED:
                        raise LoxoneConnectionError("Connection is closed")

                    try:
                        message = await asyncio.wait_for(
                            connection.recv_message(),
                            timeout=self.timeout or TIMEOUT * 2,
                        )
                    except asyncio.TimeoutError:
                        _LOGGER.warning("Timeout receiving message")
                        continue
                    except websockets.exceptions.ConnectionClosedOK:
                        _LOGGER.debug(
                            "Task ConnectionClosedOK received — converting to LoxoneConnectionError"
                        )
                        raise LoxoneConnectionError(
                            "Connection closed (normal)"
                        ) from None
                    except websockets.exceptions.ConnectionClosedError as e:
                        _LOGGER.error(f"Connection closed with error: {e}")
                        raise LoxoneConnectionError(f"Connection closed: {e}") from None
                    except websockets.exceptions.ConnectionClosed:
                        _LOGGER.error("Connection closed")
                        raise LoxoneConnectionError("Connection closed") from None
                    except Exception as e:
                        _LOGGER.error(f"Connection closed with error: {e}")
                        raise e from None
                    try:
                        await self._websocket_event(message)
                    except LoxoneTokenError:
                        raise
                    except Exception as e:
                        _LOGGER.error(
                            f"Error processing websocket event: {e}", exc_info=True
                        )
                        # Continue listening despite processing errors
                    if callback and message.message_type in [
                        MessageType.VALUE_STATES,
                        MessageType.TEXT_STATES,
                        MessageType.TEXT,
                        MessageType.KEEPALIVE,
                    ]:
                        try:
                            awaitable = callback(message.as_dict())
                            if awaitable:
                                await awaitable
                        except Exception as e:
                            _LOGGER.error(f"Callback error: {e}", exc_info=True)
                    else:
                        _LOGGER.debug(
                            f"Message type {list(MessageType)[message.message_type].name} not handled yet ..."
                        )
                        _ = message.as_dict()
                        if _ != {}:
                            _LOGGER.debug(f"Message {message.as_dict()}")

                except asyncio.CancelledError:
                    raise
                except LoxoneConnectionError:
                    raise
                except Exception as e:
                    _LOGGER.error(f"Error in listening loop: {e}", exc_info=True)
                    # Add a small delay to avoid tight loop on persistent errors
                    raise
        except LoxoneTokenError:
            raise
        except LoxoneOutOfServiceException:
            raise
        except asyncio.CancelledError:
            _LOGGER.debug("Listening task cancelled")
            raise
        except Exception as e:
            _LOGGER.error(f"Listening task failed: {e}")
            raise

    async def open(
        self, session: aiohttp.ClientSession | None = None
    ) -> LoxoneClientConnection:

        if self._closed:
            raise RuntimeError("Cannot open a closed connection")

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

            try:
                data = await asyncio.wait_for(
                    api_resp.content.read(), timeout=self.timeout or TIMEOUT
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Timeout reading API key response")
            except Exception as e:
                raise RuntimeError(f"Failed to read API key response: {e}") from e

            try:
                _value = LLResponse(data).value
            except Exception as e:
                raise ValueError(f"Invalid API key response format: {e}") from e

            # The json returned by the miniserver is invalid. It contains " and '.
            # We need to normalise it
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
                    connector.base_url = str(api_resp.url).replace(CMD_GET_API_KEY, "")
                    self.url = connector.base_url.replace("https://", "").replace(
                        "http://", ""
                    )
                except Exception as e:
                    _LOGGER.warning(f"Failed to update URL for remote access: {e}")

            # Get the structure file
            try:
                lox_app_data = await connector.get(LOXAPPPATH)
            except Exception as e:
                _LOGGER.error(f"Failed to get structure file: {e}", exc_info=True)
                raise

            if lox_app_data.status != 200:
                raise RuntimeError(
                    f"Failed to get structure file, status: {lox_app_data.status}"
                )

            try:
                data = await asyncio.wait_for(
                    lox_app_data.content.read(), timeout=self.timeout or TIMEOUT
                )
                self.structure_file = json.loads(data)
                self.structure_file["softwareVersion"] = (
                    self.miniserver_version
                )  # FIXME Legacy use only. Need to fix pyloxone
            except asyncio.TimeoutError:
                raise TimeoutError("Timeout reading structure file")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in structure file: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Failed to read structure file: {e}") from e

            # Get the public key
            try:
                pk_data = await connector.get(CMD_GET_PUBLIC_KEY)
            except Exception as e:
                raise RuntimeError(f"Failed to get public key: {e}") from e

            try:
                pk_data_text = await asyncio.wait_for(
                    pk_data.content.read(), timeout=self.timeout or TIMEOUT
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Timeout reading public key")
            except Exception as e:
                raise RuntimeError(f"Failed to read public key: {e}") from e

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

        # generate first salt
        try:
            self._generate_salt()
        except Exception as e:
            _LOGGER.error(f"Failed to generate initial salt: {e}")
            raise

        # Establish websocket connection
        try:
            params = {"url": self.url}
            if self.scheme == "https":
                base_url = self._SSL_URL_FORMAT.format(**params)
            else:
                base_url = self._URL_FORMAT.format(**params)

            try:
                connection = await asyncio.wait_for(
                    wslib.connect(
                        base_url,
                        open_timeout=self.timeout or TIMEOUT,
                        create_connection=LoxoneClientConnection,
                        compression=None,
                        max_size=MAX_WEBSOCKET_MESSAGE_SIZE,
                    ),
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
            return connection

        except Exception as e:
            _LOGGER.error(f"Failed to establish websocket connection: {e}")
            raise

    async def close(self) -> None:
        """Gracefully close the connection and drain message queues."""
        if self._closed:
            _LOGGER.debug("Connection already closed")
            return

        _LOGGER.debug("Closing connection...")
        self._closed = True

        # Signal shutdown to all tasks
        self._shutdown_event.set()

        # Wait for message queue to drain (with timeout)
        if self._message_queue:
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

    async def send_websocket_command(
        self, device_uuid: str, value: Union[str, int, float]
    ):
        """Send a websocket command to the Miniserver.

        value may be a str, int or float — it will be converted to string when sent.
        """

        if not device_uuid or not isinstance(device_uuid, str):
            raise ValueError("device_uuid must be a non-empty string")

        if value is None or not isinstance(value, (str, int, float)):
            raise ValueError("value must be a string, int, or float")

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

    async def send_secured__websocket_command(
        self, device_uuid: str, value: Union[str, int, float], code: str
    ):
        if not device_uuid or not isinstance(device_uuid, str):
            raise ValueError("device_uuid must be a non-empty string")
        if value is None or not isinstance(value, (str, int, float)):
            raise ValueError("value must be a string, int, or float")
        if not code or not isinstance(code, str):
            raise ValueError("code must be a non-empty string")

        try:
            command = f"{CMD_GET_VISUAL_PASSWD}{self.username}"
            _LOGGER.debug(f"Call send_secured__websocket_command: {command}")

            try:
                # Use put_nowait with QueueFull exception handling
                self._secured_queue.put_nowait(
                    self._send_secure(device_uuid, value, code)
                )
                self._message_queue.put_nowait(
                    MessageForQueue(command=command, flag=True)
                )
            except asyncio.QueueFull:
                _LOGGER.error("Queue is full, dropping secured command")
                raise RuntimeError("Queue is full, cannot send secured command")
        except Exception as e:
            _LOGGER.error(f"Failed to send secured websocket command: {e}")
            raise

    async def _websocket_event(self, message: Dict[str, Any] | BaseMessage) -> None:
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
                command = f"{CMD_GET_KEY_AND_SALT}/{self.username}"
                try:
                    # Use put() for critical protocol messages
                    await asyncio.wait_for(
                        self._message_queue.put(MessageForQueue(command, True)),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    _LOGGER.error("Timeout queueing key exchange command")

            # Handle getkey2
            elif isinstance(mess_obj, TextMessage) and "getkey2" in mess_obj.message:
                _LOGGER.debug("Got get key2")
                try:
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")

                    self._key = value_dict.get("key", "")
                    self._user_salt = value_dict.get("salt", "")
                    self._hash_alg = value_dict.get("hashAlg")

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
                            CMD_AUTH_WITH_TOKEN, token_hash, self.username
                        )
                        await asyncio.wait_for(
                            self._message_queue.put(MessageForQueue(command, True)),
                            timeout=1.0,
                        )
                    else:
                        _LOGGER.debug("Acquire new token...")
                        new_hash = self._hash_credentials()
                        if new_hash is None:
                            raise RuntimeError("Failed to hash credentials")

                        # Request new Token
                        if self.miniserver_version < [10, 2]:
                            command = f"{CMD_REQUEST_TOKEN}/{new_hash}/{self.username}/{TOKEN_PERMISSION}/edfc5f9a-df3f-4cad-9dddcdc42c732b82/pyloxone_api"
                        else:
                            command = f"{CMD_REQUEST_TOKEN_JSON_WEB}/{new_hash}/{self.username}/{TOKEN_PERMISSION}/edfc5f9a-df3f-4cad-9dddcdc42c732b82/pyloxone_api"
                        await asyncio.wait_for(
                            self._message_queue.put(MessageForQueue(command, True)),
                            timeout=1.0,
                        )

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
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")
                    self._key = value_dict.get("value", "")
                    # Signal that key has been updated
                    if self._key_update_event is not None:
                        self._key_update_event.set()

                except Exception as e:
                    _LOGGER.error(f"Error processing getkey: {e}")

            # Handle visual salt
            elif (
                isinstance(mess_obj, TextMessage) and "getvisusalt" in mess_obj.message
            ):
                try:
                    value_dict = mess_obj.value_as_dict
                    if not isinstance(value_dict, dict):
                        raise ValueError("value_as_dict is not a dictionary")
                    self._key = value_dict.get("value", "")

                    key_and_salt = LxJsonKeySalt()
                    key_and_salt.read_user_salt_response(mess_obj.message)
                    key_and_salt.time_elapsed_in_seconds = time_elapsed_in_seconds()
                    self._visual_hash = key_and_salt

                    while not self._secured_queue.empty():
                        try:
                            awaitable = self._secured_queue.get_nowait()
                            if awaitable:
                                await awaitable
                            self._secured_queue.task_done()
                        except asyncio.QueueEmpty:
                            break
                        except Exception as e:
                            _LOGGER.error(f"Error processing secured queue item: {e}")

                except Exception as e:
                    _LOGGER.error(f"Error processing visual salt: {e}")

            # Handle token response
            elif isinstance(mess_obj, TextMessage) and (
                "gettoken" in mess_obj.message or "getjwt" in mess_obj.message
            ):
                try:
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

                    await asyncio.wait_for(
                        self._message_queue.put(
                            MessageForQueue(f"{CMD_ENABLE_UPDATES}", True)
                        ),
                        timeout=1.0,
                    )

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
                    _LOGGER.error("Token authentication failed (401)")
                    self.reset_token()
                    raise LoxoneTokenError from None
                else:
                    _LOGGER.debug("Got message authwithtoken")
                    try:
                        await asyncio.wait_for(
                            self._message_queue.put(
                                MessageForQueue(f"{CMD_ENABLE_UPDATES}", True)
                            ),
                            timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        _LOGGER.error("Timeout queueing authwithtoken command")

            # Handle token refresh
            elif isinstance(mess_obj, TextMessage) and (
                "refreshjwt" in mess_obj.message or "refresh" in mess_obj.message
            ):
                _LOGGER.debug(f"Got token refresh response")
                try:
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
                        f"Token refreshed successfully, valid until: {valid_until}"
                    )

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

        except Exception as e:
            _LOGGER.error(f"Error in websocket event handler: {e}", exc_info=True)
