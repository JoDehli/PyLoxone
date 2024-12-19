"""
Loxone Api

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import asyncio
import binascii
import datetime
import hashlib
import json
import logging
import queue
import time
import traceback
import urllib.request as req
import uuid
from base64 import b64encode
from datetime import datetime
from math import floor
from struct import unpack

import httpx
import websockets.legacy.client as wslib
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import HMAC, SHA1, SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Util import Padding

from .const import (AES_KEY_SIZE, CMD_AUTH_WITH_TOKEN, CMD_ENABLE_UPDATES,
                    CMD_ENCRYPT_CMD, CMD_GET_KEY, CMD_GET_KEY_AND_SALT,
                    CMD_GET_PUBLIC_KEY, CMD_GET_VISUAL_PASSWD,
                    CMD_KEY_EXCHANGE, CMD_REFRESH_TOKEN,
                    CMD_REFRESH_TOKEN_JSON_WEB, CMD_REQUEST_TOKEN,
                    CMD_REQUEST_TOKEN_JSON_WEB, DEFAULT_TOKEN_PERSIST_NAME,
                    ERROR_VALUE, IV_BYTES, KEEP_ALIVE_PERIOD, LOXAPPPATH,
                    SALT_BYTES, SALT_MAX_AGE_SECONDS, SALT_MAX_USE_COUNT,
                    TIMEOUT, TOKEN_PERMISSION, TOKEN_REFRESH_RETRY_COUNT)

_LOGGER = logging.getLogger(__name__)

class LoxoneException(Exception):
    """Base class for all Loxone Exceptions"""


class LoxoneHTTPStatusError(LoxoneException):
    """An exception indicating an unusual http response from the miniserver"""


class LoxoneRequestError(Exception):
    """An exception raised during an http request"""


async def raise_if_not_200(response: httpx.Response) -> None:
    """A httpx event hook, to ensure that http responses other than 200
    raise an exception"""
    # Loxone response codes are a bit odd. It is not clear whether a response which
    # is not 200 is ever OK (eg it is unclear whether redirect response are issued).
    # json responses also have a "Code" key, but it is unclear whether this is ever
    # different from the http response code. At the moment, we ignore it.
    #
    # And there are references to non-standard codes in the docs (eg a 900 error).
    # At present, treat any non-200 code as an exception.
    if response.status_code != 200:
        if response.is_stream_consumed:
            raise LoxoneHTTPStatusError(
                f"Code {response.status_code}. Miniserver response was {response.text}"
            )
        else:
            raise LoxoneHTTPStatusError(
                f"Miniserver response code {response.status_code}"
            )


class LoxApp(object):
    def __init__(self):
        """Initialize the LoxApp object."""
        self.host = None
        self.port = None
        self.loxapppath = LOXAPPPATH

        self.lox_user = None
        self.lox_pass = None
        self.json = None
        self.responsecode = None
        self.version = None
        self.https_status = None
        self.url = ""
        self._local = True

    async def get_json(self):
        """Get the json data from the Loxone Miniserver."""
        auth = None
        if self.lox_user is not None and self.lox_pass is not None:
            auth = (self.lox_user, self.lox_pass)

        if self.port == 80:
            if self.host.find("http://") > -1:
                _base_url = "{}".format(self.host)
            else:
                _base_url = "http://{}".format(self.host)
        elif self.port == 443:
            if self.host.find("https://") > -1:
                _base_url = "{}".format(self.host)
            else:
                _base_url = "https://{}".format(self.host)
        else:
            _base_url = "http://{}:{}".format(self.host, self.port)
        self.url = _base_url
        client = httpx.AsyncClient(
            auth=auth,
            base_url=_base_url,
            verify=False,
            follow_redirects=True,
            timeout=TIMEOUT,
            event_hooks={"response": [raise_if_not_200]},
        )

        api_resp = await client.get("/jdev/cfg/apiKey")

        if api_resp.status_code != 200:
            _LOGGER.error(
                f"Could not connect to Loxone! Status code {api_resp.status_code}."
            )
            return False

        req_data = api_resp.json()
        self._local = True
        if "LL" in req_data:
            if "Code" in req_data["LL"] and "value" in req_data["LL"]:
                _ = req_data["LL"]["value"]
                value = json.loads(_.replace("'", '"'))
                self.https_status = value.get("httpsStatus")
                self.version = [int(x) for x in value.get("version").split(".")]
                self._local = value.get("local", True)

        if not self._local:
            _base_url = str(api_resp.url).replace("/jdev/cfg/apiKey", "")
            await client.aclose()
            client = httpx.AsyncClient(
                auth=auth,
                base_url=_base_url,
                verify=True,
                follow_redirects=True,
                timeout=TIMEOUT,
                event_hooks={"response": [raise_if_not_200]},
            )
            self.url = _base_url

        my_response = await client.get(LOXAPPPATH)

        if my_response.status_code == 200:
            self.json = my_response.json()
            if self.version is not None:
                self.json["softwareVersion"] = self.version
        else:
            self.json = None
        self.responsecode = my_response.status_code
        await client.aclose()
        return self.responsecode


class LoxWs:
    """Loxone Websocket class."""

    def __init__(
        self,
        user=None,
        password=None,
        host="http://192.168.1.225 ",
        port="8080",
        token_persist_filename=None,
        loxconfig=None,
        loxone_url=None,
    ):
        self._username = user
        self._pasword = password
        self._host = host
        self._port = port
        self._loxone_url = loxone_url
        self._token_refresh_count = TOKEN_REFRESH_RETRY_COUNT
        self._token_persist_filename = token_persist_filename
        self._loxconfig = loxconfig
        self._version = 0
        self._recv_lock = asyncio.Lock()
        if self._loxconfig is not None:
            if "softwareVersion" in self._loxconfig:
                vers = self._loxconfig["softwareVersion"]
                if isinstance(vers, list) and len(vers) >= 2:
                    try:
                        self._version = float("{}.{}".format(vers[0], vers[1]))
                    except ValueError:
                        self._version = 0

        if self._token_persist_filename is None:
            self._token_persist_filename = DEFAULT_TOKEN_PERSIST_NAME

        self._iv = gen_init_vec()
        self._key = gen_key()
        self._token = LxToken()
        self._token_valid_until = 0
        self._salt = ""
        self._salt_used_count = 0
        self._salt_time_stamp = 0
        self._public_key = None
        self._rsa_cipher = None
        self._session_key = None
        self._ws = None
        self._current_message_type = None
        self._encryption_ready = False
        self._visual_hash = None
        self._keep_alive_task = None

        self.message_call_back = None
        self.background_tasks = set()

        self.connect_retries = 20
        self.connect_delay = 15
        self.state = "CLOSED"
        self._secured_queue = queue.Queue(maxsize=1)

    @property
    def token_as_dict(self):
        """Return the token as a dictionary."""
        return self._token.__dict__

    def set_token_from_dict(self, token_dict: dict):
        """Set the token from a dictionary"""
        self._token = LxToken(
            token=token_dict["token"],
            hash_alg=token_dict["hash_alg"],
            valid_until=token_dict["valid_until"],
        )

    @property
    def key(self):
        """Return the key."""
        return self._key

    @property
    def iv(self):
        """Return the iv."""
        return self._iv

    async def refresh_token(self):
        """Refresh the token."""
        try:
            while True:
                seconds_to_refresh = self._token.get_seconds_to_expire()
                await asyncio.sleep(seconds_to_refresh)
                self._token = LxToken()
                # raise ConnectionResetError
        except Exception as e:
            raise e

    async def decrypt(self, message):
        """Decrypt the message."""
        pass

    async def _refresh_token(self):
        """Refresh the token."""

        _LOGGER.debug("Try to refresh token.")
        # Send command to get the key
        command = "{}".format(CMD_GET_KEY)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e        
        resp_json = json.loads(message)
        token_hash = None

        # Check if the response contains the key
        if "LL" in resp_json and "value" in resp_json["LL"]:
            key = resp_json["LL"]["value"]
            if key == "":
                # Determine the hash algorithm based on the version
                hash_alg = SHA1 if self._version < 12.0 else SHA256
                digester = HMAC.new(
                    binascii.unhexlify(key),
                    self._token.token.encode("utf-8"),
                    hash_alg,
                )
                token_hash = digester.hexdigest()

        if token_hash:
            command = "{}{}/{}".format(
                (
                    CMD_REFRESH_TOKEN
                    if self._version < 10.2
                    else CMD_REFRESH_TOKEN_JSON_WEB
                ),
                token_hash,
                self._username,
            )

            enc_command = await self.encrypt(command)
            await self._ws.send(enc_command)
            try:
                async with self._recv_lock:
                    message = await self._ws.recv()
                # Handle the received message
            except Exception as e:
                raise e            
            resp_json = json.loads(message)

            _LOGGER.debug(
                "Seconds before refresh: {}".format(self._token.get_seconds_to_expire())
            )

            if (
                "LL" in resp_json
                and "value" in resp_json["LL"]
                and "validUntil" in resp_json["LL"]["value"]
            ):
                self._token.set_valid_until(resp_json["LL"]["value"]["validUntil"])

    async def start(self) -> None:
        """Start the websocket connection."""
        _LOGGER.debug("Starting websocket connection")
        tasks = [
            asyncio.create_task(self.ws_listen(), name="consumer_task"),
            asyncio.create_task(self.keep_alive(KEEP_ALIVE_PERIOD), name="keepalive"),
            asyncio.create_task(self.refresh_token(), name="refresh_token"),
        ]
        for task in tasks:
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

    async def reconnect(self) -> None:
        """Reconnect the websocket."""
        for attempt in range(self.connect_retries):
            _LOGGER.debug(f"Reconnect attempt {attempt + 1} of {self.connect_retries}")
            await self.stop()
            self.state = "CONNECTING"
            _LOGGER.debug(
                f"Waiting for {self.connect_delay} seconds before retrying..."
            )
            await asyncio.sleep(self.connect_delay)
            res = await self.async_init()
            if res is True:
                _LOGGER.debug("Reconnection successful.")
                await self.start()
                self.state = "CONNECTED"
                break
            else:
                _LOGGER.debug("Reconnection failed.")
        else:
            _LOGGER.error("All reconnection attempts failed.")
            self.state = "CLOSED"

    # https://github.com/aio-libs/aiohttp/issues/754
    async def stop(self) -> int:
        try:
            _LOGGER.debug("Stopping integration")
            if self.background_tasks:
                # Iterate over a copy of the background_tasks set to avoid modifying it during iteration
                for task in list(self.background_tasks):  # Convert set to list to safely modify during iteration
                    _LOGGER.debug(f"Cancelling task: {task.get_name()}")
                    task.cancel()
                    try:
                        # Await the cancellation of each task to ensure cleanup
                        await task
                    except asyncio.CancelledError:
                        _LOGGER.debug(f"Task {task.get_name()} was cancelled")
            self.state = "STOPPING"
            if not self._ws.closed:
                await self._ws.close()
            return 1
        except Exception as e:
            _LOGGER.error(e)
            return -1

    async def keep_alive(self, second: int) -> None:
        try:
            while True:
                await asyncio.sleep(second)
                if self._encryption_ready:
                    async with asyncio.Lock():
                        await self._ws.send("keepalive")
        except Exception as e:
            raise e

    async def send_secured(self, device_uuid: str, value: str, code: str):

        pwd_hash_str = str(code) + ":" + self._visual_hash.salt
        if self._visual_hash.hash_alg == "SHA1":
            m = hashlib.sha1()
        elif self._visual_hash.hash_alg == "SHA256":
            m = hashlib.sha256()
        else:
            _LOGGER.error(
                "Unrecognised hash algorithm: {}".format(self._visual_hash.hash_alg)
            )
            return -1

        m.update(pwd_hash_str.encode("utf-8"))
        pwd_hash = m.hexdigest().upper()
        digester = HMAC.new(
            binascii.unhexlify(self._visual_hash.key),
            pwd_hash.encode("utf-8"),
            SHA1 if self._visual_hash.hash_alg == "SHA1" else SHA256,
        )

        command = "jdev/sps/ios/{}/{}/{}".format(
            digester.hexdigest(), device_uuid, value
        )
        await self._ws.send(command)

    async def send_secured__websocket_command(
        self, device_uuid: str, value: str, code: str
    ) -> None:
        self._secured_queue.put((device_uuid, value, code))
        await self.get_visual_hash()

    async def send_websocket_command(self, device_uuid: str, value: str) -> None:
        """Send a websocket command to the Miniserver."""
        command = "jdev/sps/io/{}/{}".format(device_uuid, value)
        _LOGGER.debug("Send command: {}".format(command))
        await self._ws.send(command)

    async def async_init(self):
        # Get public key from Loxone
        resp = await self.get_public_key()

        if not resp:
            return ERROR_VALUE

        # Init resa cipher
        rsa_gen = self.init_rsa_cipher()
        if not rsa_gen:
            return ERROR_VALUE

        # Generate session key
        session_gen = self.generate_session_key()
        if not session_gen:
            return ERROR_VALUE

        # Exchange keys
        try:
            if self._loxone_url.startswith("https:"):
                new_url = self._loxone_url.replace("https", "wss")
            else:
                new_url = self._loxone_url.replace("http", "ws")

            self._ws = await wslib.connect(
                "{}/ws/rfc6455".format(new_url), timeout=TIMEOUT
            )

            await self._ws.send("{}{}".format(CMD_KEY_EXCHANGE, self._session_key))

            try:
                async with self._recv_lock:
                    message = await self._ws.recv()
            except Exception as e:
                raise e
            await self.parse_loxone_message(message)
            if self._current_message_type != 0:
                _LOGGER.debug("Error getting the session key response")
                return ERROR_VALUE

            try:
                async with self._recv_lock:
                    message = await self._ws.recv()
                # Handle the received message
            except Exception as e:
                raise e
            resp_json = json.loads(message)
            if "LL" in resp_json:
                if "Code" in resp_json["LL"]:
                    if resp_json["LL"]["Code"] != "200":
                        return ERROR_VALUE
            else:
                return ERROR_VALUE

        except ConnectionError:
            _LOGGER.debug("Connection error...")
            return ERROR_VALUE

        self._encryption_ready = True

        if (
            self._token is None
            or self._token.token == ""
            or self._token.get_seconds_to_expire() < 300
        ):
            res = await self.acquire_token()
        else:
            _LOGGER.debug("use loaded token...")
            res = await self.use_token()
            # Delete old token
            if res is ERROR_VALUE:
                _LOGGER.debug(
                    "Old Token found and deleted. Please restart Homeassistant to aquire new token."
                )
                return -500

        if res is ERROR_VALUE:
            return ERROR_VALUE

        if self._ws.closed:
            _LOGGER.debug(f"Connection closed. Reason {self._ws.close_code}")
            return False

        command = "{}".format(CMD_ENABLE_UPDATES)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        if self._ws.closed:
            _LOGGER.debug(f"Connection closed. Reason {self._ws.close_code}")
            return False
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e            

        self.state = "CONNECTED"
        return True

    async def get_visual_hash(self) -> None:
        command = "{}{}".format(CMD_GET_VISUAL_PASSWD, self._username)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)

    async def ws_listen(self) -> None:
        try:
            while True:
                try:
                    async with self._recv_lock:
                        message = await self._ws.recv()
                    # Handle the received message
                except Exception as e:
                    raise e
                await self._async_process_message(message)
                await asyncio.sleep(0)
        except Exception as e:
            _LOGGER.debug(f"ws_listen exception: {e}")
            await asyncio.sleep(5)
            if self._ws.closed and self._ws.close_code in [4004, 4005]:
                self._token = LxToken()

            elif self._ws.closed and self._ws.close_code:
                await self.reconnect()
            else:
                raise e

    async def _async_process_message(self, message: str) -> None:
        if len(message) == 8:
            unpacked_data = unpack("ccccI", message)
            self._current_message_type = int.from_bytes(
                unpacked_data[1], byteorder="big"
            )
            if self._current_message_type == 6:
                _LOGGER.debug("Keep alive response received...")
        else:
            parsed_data = await self._parse_loxone_message(message)
            # if parsed_data != {}:
            #     _LOGGER.debug(
            #         "message [type:{}]):{}".format(
            #             self._current_message_type, parsed_data
            #         )
            #     )

            try:
                resp_json = json.loads(parsed_data)
            except TypeError:
                resp_json = None

            # Visual hash and key response
            if resp_json is not None and "LL" in resp_json:
                if (
                    "control" in resp_json["LL"]
                    and "code" in resp_json["LL"]
                    and resp_json["LL"]["code"] in [200, "200"]
                ):
                    if "value" in resp_json["LL"]:
                        if (
                            "key" in resp_json["LL"]["value"]
                            and "salt" in resp_json["LL"]["value"]
                        ):
                            key_and_salt = LxJsonKeySalt()
                            key_and_salt.read_user_salt_responce(parsed_data)
                            key_and_salt.time_elapsed_in_seconds = (
                                time_elapsed_in_seconds()
                            )
                            self._visual_hash = key_and_salt

                            while not self._secured_queue.empty():
                                secured_message = self._secured_queue.get()
                                await self.send_secured(
                                    secured_message[0],
                                    secured_message[1],
                                    secured_message[2],
                                )

            if self.message_call_back is not None:
                if "LL" not in parsed_data and parsed_data != {}:
                    await self.message_call_back(parsed_data)
            self._current_message_type = None
            await asyncio.sleep(0)

    async def _parse_loxone_message(self, message):
        """Parser of the Loxone message."""
        event_dict = {}
        if self._current_message_type == 0:
            event_dict = message
        elif self._current_message_type == 1:
            pass
        elif self._current_message_type == 2:
            length = len(message)
            num = length / 24
            start = 0
            end = 24
            for i in range(int(num)):
                packet = message[start:end]
                event_uuid = uuid.UUID(bytes_le=packet[0:16])
                fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
                uuidstr = "{}-{}-{}-{}{}".format(
                    fields[0], fields[1], fields[2], fields[3], fields[4]
                )
                value = unpack("d", packet[16:24])[0]
                event_dict[uuidstr] = value
                start += 24
                end += 24
        elif self._current_message_type == 3:

            start = 0

            def get_text(msg, head, offset):
                first = head
                second = head + offset
                event_uuid = uuid.UUID(bytes_le=msg[first:second])
                first += offset
                second += offset

                icon_uuid_fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
                uuidstr = "{}-{}-{}-{}{}".format(
                    icon_uuid_fields[0],
                    icon_uuid_fields[1],
                    icon_uuid_fields[2],
                    icon_uuid_fields[3],
                    icon_uuid_fields[4],
                )

                icon_uuid = uuid.UUID(bytes_le=msg[first:second])
                icon_uuid_fields = icon_uuid.urn.replace("urn:uuid:", "").split("-")
                uuidiconstr = "{}-{}-{}-{}{}".format(
                    icon_uuid_fields[0],
                    icon_uuid_fields[1],
                    icon_uuid_fields[2],
                    icon_uuid_fields[3],
                    icon_uuid_fields[4],
                )

                first = second
                second += 4

                text_length = unpack("<I", msg[first:second])[0]

                first = second
                second = first + text_length
                message_str = unpack("{}s".format(text_length), msg[first:second])[0]
                head += (floor((4 + text_length + 16 + 16 - 1) / 4) + 1) * 4
                event_dict[uuidstr] = message_str.decode("utf-8")
                return head

            while start < len(message):
                start = get_text(message, start, 16)

        elif self._current_message_type == 6:
            event_dict["keep_alive"] = "received"
        else:
            self._current_message_type = 7
        return event_dict

    async def use_token(self):
        token_hash = await self.hash_token()
        if token_hash is ERROR_VALUE:
            return ERROR_VALUE
        command = "{}{}/{}".format(CMD_AUTH_WITH_TOKEN, token_hash, self._username)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e
        await self.parse_loxone_message(message)
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e
        resp_json = json.loads(message)
        if "LL" in resp_json:
            if "code" in resp_json["LL"]:
                if resp_json["LL"]["code"] == "200":
                    if "value" in resp_json["LL"]:
                        self._token.set_valid_until(
                            resp_json["LL"]["value"]["validUntil"]
                        )
                    return True
        return ERROR_VALUE

    async def hash_token(self):
        try:

            command = "{}".format(CMD_GET_KEY)
            enc_command = await self.encrypt(command)
            await self._ws.send(enc_command)
            try:
                async with self._recv_lock:
                    message = await self._ws.recv()
                # Handle the received message
            except Exception as e:
                raise e
            await self.parse_loxone_message(message)
            try:
                async with self._recv_lock:
                    message = await self._ws.recv()
                # Handle the received message
            except Exception as e:
                raise e
            resp_json = json.loads(message)
            if "LL" in resp_json:
                if "value" in resp_json["LL"]:
                    key = resp_json["LL"]["value"]
                    if key != "":
                        if self._token.hash_alg == "SHA1":
                            digester = HMAC.new(
                                binascii.unhexlify(key),
                                self._token.token.encode("utf-8"),
                                SHA1,
                            )
                        elif self._token.hash_alg == "SHA256":
                            digester = HMAC.new(
                                binascii.unhexlify(key),
                                self._token.token.encode("utf-8"),
                                SHA256,
                            )
                        else:
                            _LOGGER.error(
                                "Unrecognised hash algorithm: {}".format(
                                    self._token.hash_alg
                                )
                            )
                            return ERROR_VALUE

                        return digester.hexdigest()
            return ERROR_VALUE
        except Exception as e:
            _LOGGER.error(e)
            return ERROR_VALUE

    async def acquire_token(self):
        command = "{}{}".format(CMD_GET_KEY_AND_SALT, self._username)
        enc_command = await self.encrypt(command)

        if not self._encryption_ready or self._ws is None:
            return ERROR_VALUE

        await self._ws.send(enc_command)
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e
        await self.parse_loxone_message(message)

        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e

        key_and_salt = LxJsonKeySalt()
        key_and_salt.read_user_salt_responce(message)

        new_hash = self.hash_credentials(key_and_salt)

        if self._version < 10.2:
            command = (
                "{}{}/{}/{}/edfc5f9a-df3f-4cad-9dddcdc42c732be2"
                "/homeassistant".format(
                    CMD_REQUEST_TOKEN, new_hash, self._username, TOKEN_PERMISSION
                )
            )
        else:
            command = (
                "{}{}/{}/{}/edfc5f9a-df3f-4cad-9dddcdc42c732be2"
                "/homeassistant".format(
                    CMD_REQUEST_TOKEN_JSON_WEB,
                    new_hash,
                    self._username,
                    TOKEN_PERMISSION,
                )
            )

        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e
        await self.parse_loxone_message(message)
        try:
            async with self._recv_lock:
                message = await self._ws.recv()
            # Handle the received message
        except Exception as e:
            raise e

        resp_json = json.loads(message)
        if "LL" in resp_json:
            if "value" in resp_json["LL"]:
                if (
                    "token" in resp_json["LL"]["value"]
                    and "validUntil" in resp_json["LL"]["value"]
                ):
                    self._token = LxToken(
                        resp_json["LL"]["value"]["token"],
                        resp_json["LL"]["value"]["validUntil"],
                        key_and_salt.hash_alg,
                    )
                    _LOGGER.debug(f"Token: {self._token.get_seconds_to_expire()}")
        return True

    async def encrypt(self, command):

        if not self._encryption_ready:
            return command
        if self._salt != "" and self.new_salt_needed():
            prev_salt = self._salt
            self._salt = self.genarate_salt()
            s = "nextSalt/{}/{}/{}\0".format(prev_salt, self._salt, command)
        else:
            if self._salt == "":
                self._salt = self.genarate_salt()
            s = "salt/{}/{}\0".format(self._salt, command)
        s = Padding.pad(bytes(s, "utf-8"), 16)
        aes_cipher = self.get_new_aes_chiper()
        encrypted = aes_cipher.encrypt(s)
        encoded = b64encode(encrypted)
        encoded_url = req.pathname2url(encoded.decode("utf-8"))
        return CMD_ENCRYPT_CMD + encoded_url

    def hash_credentials(self, key_salt):
        try:

            pwd_hash_str = self._pasword + ":" + key_salt.salt
            if key_salt.hash_alg == "SHA1":
                m = hashlib.sha1()
            elif key_salt.hash_alg == "SHA256":
                m = hashlib.sha256()
            else:
                _LOGGER.error(
                    "Unrecognised hash algorithm: {}".format(key_salt.hash_alg)
                )
                return None

            m.update(pwd_hash_str.encode("utf-8"))
            pwd_hash = m.hexdigest().upper()
            pwd_hash = self._username + ":" + pwd_hash

            digester = HMAC.new(
                binascii.unhexlify(key_salt.key),
                pwd_hash.encode("utf-8"),
                SHA1 if key_salt.hash_alg == "SHA1" else SHA256,
            )

            _LOGGER.debug("hash_credentials successfully...")
            return digester.hexdigest()
        except ValueError:
            _LOGGER.debug("error hash_credentials...")
            return None

    def genarate_salt(self):

        salt = get_random_bytes(SALT_BYTES)
        salt = binascii.hexlify(salt).decode("utf-8")
        salt = req.pathname2url(salt)
        self._salt_time_stamp = time_elapsed_in_seconds()
        self._salt_used_count = 0
        return salt

    def new_salt_needed(self):
        self._salt_used_count += 1
        if (
            self._salt_used_count > SALT_MAX_USE_COUNT
            or time_elapsed_in_seconds() - self._salt_time_stamp > SALT_MAX_AGE_SECONDS
        ):
            return True
        return False

    async def parse_loxone_message(self, message):
        if len(message) == 8:
            try:
                unpacked_data = unpack("ccccI", message)
                self._current_message_type = int.from_bytes(
                    unpacked_data[1], byteorder="big"
                )
                _LOGGER.debug("parse_loxone_message successfully...")
            except ValueError:
                _LOGGER.debug("error parse_loxone_message...")

    def generate_session_key(self):
        try:
            aes_key = binascii.hexlify(self._key).decode("utf-8")
            iv = binascii.hexlify(self._iv).decode("utf-8")
            sess = aes_key + ":" + iv
            sess = self._rsa_cipher.encrypt(bytes(sess, "utf-8"))
            self._session_key = b64encode(sess).decode("utf-8")
            _LOGGER.debug("generate_session_key successfully...")
            return True
        except KeyError:
            _LOGGER.debug("error generate_session_key...")
            return False

    def get_new_aes_chiper(self):
        try:

            _new_aes = AES.new(self._key, AES.MODE_CBC, self._iv)
            _LOGGER.debug("get_new_aes_chiper successfully...")
            return _new_aes
        except ValueError:
            _LOGGER.debug("error get_new_aes_chiper...")
            return None

    def init_rsa_cipher(self):
        try:
            self._public_key = self._public_key.replace(
                "-----BEGIN CERTIFICATE-----", "-----BEGIN PUBLIC KEY-----\n"
            )
            public_key = self._public_key.replace(
                "-----END CERTIFICATE-----", "\n-----END PUBLIC KEY-----\n"
            )
            self._rsa_cipher = PKCS1_v1_5.new(RSA.importKey(public_key))
            _LOGGER.debug("init_rsa_cipher successfully...")
            return True
        except KeyError:
            _LOGGER.debug("init_rsa_cipher error...")
            _LOGGER.debug("{}".format(traceback.print_exc()))
            return False

    async def get_public_key(self):
        command = f"{self._loxone_url}/{CMD_GET_PUBLIC_KEY}"
        _LOGGER.debug("try to get public key: {}".format(command))
        try:
            client = httpx.AsyncClient(
                auth=(self._username, self._pasword),
                base_url=self._loxone_url,
                follow_redirects=True,
                verify=False,
                timeout=TIMEOUT,
                event_hooks={"response": [raise_if_not_200]},
            )
            response = await client.get(f"/{CMD_GET_PUBLIC_KEY}")
            await client.aclose()
        except Exception as e:
            _LOGGER.error(e)
            return False

        if response.status_code != 200:
            _LOGGER.debug("error get_public_key: {}".format(response.status_code))
            return False
        try:
            resp_json = json.loads(response.text)
            if "LL" in resp_json and "value" in resp_json["LL"]:
                self._public_key = resp_json["LL"]["value"]
                _LOGGER.debug("get_public_key successfully...")
            else:
                _LOGGER.debug("public key load error")
                return False
        except ValueError:
            _LOGGER.debug("public key load error")
            return False
        return True


# Loxone Stuff
def gen_init_vec():

    return get_random_bytes(IV_BYTES)


def gen_key():

    return get_random_bytes(AES_KEY_SIZE)


def time_elapsed_in_seconds():
    return int(round(time.time()))


class LxJsonKeySalt:
    def __init__(self):
        self.key = None
        self.salt = None
        self.response = None
        self.time_elapsed_in_seconds = None
        self.hash_alg = None

    def read_user_salt_responce(self, reponse):
        js = json.loads(reponse, strict=False)
        value = js["LL"]["value"]
        self.key = value["key"]
        self.salt = value["salt"]
        self.hash_alg = value.get("hashAlg", "SHA1")


class LxToken:
    def __init__(self, token="", valid_until=0, hash_alg="SHA1"):
        self._token = token
        self._valid_until = valid_until
        self._hash_alg = hash_alg

    def get_seconds_to_expire(self):
        dt = datetime.strptime("1.1.2009", "%d.%m.%Y")
        try:
            start_date = int(dt.strftime("%s"))
        except Exception as e:
            _LOGGER.debug("get_seconds_to_expire error: {}".format(e))
            start_date = int(dt.timestamp())
        start_date = int(start_date) + self._valid_until
        return start_date - int(round(time.time()))

    @property
    def token(self):
        return self._token

    @property
    def valid_until(self):
        return self._valid_until

    def set_valid_until(self, value):
        self._valid_until = value

    def set_token(self, token):
        self._token = token

    @property
    def hash_alg(self):
        return self._hash_alg

    def set_hash_alg(self, hash_alg):
        self._hash_alg = hash_alg
