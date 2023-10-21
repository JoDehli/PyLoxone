import asyncio
import json
import logging
from base64 import b64encode
from collections import namedtuple
from typing import Any

import httpx
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes

from .const import (
    CMD_GET_API_KEY,
    CMD_GET_PUBLIC_KEY,
    LOXAPP,
    RETRY_INTERVALLS,
    CMD_GET_KEY_EXCHANGE,
)
from .loxone_exceptions import (
    LoxoneException,
    LoxoneMaxNumOfConnectionsError,
    LoxoneServiceUnAvailableError,
    LoxoneTimeOutError,
    LoxoneUnauthorisedError,
)
from .loxone_http_client import LoxoneAsyncHttpClient
from .loxone_types import MiniserverProtocol
from .message import LoxoneResponse

_LOGGER = logging.getLogger(__name__)


class ConnectorMixin(MiniserverProtocol):
    async def _ensure_reachable(self) -> None:
        # TODO: Check what happens with Cloud server and external access
        if self._http_client is None or self._http_client.closed:  # type: ignore
            scheme = "https" if self._use_tls else "http"
            self._http_base_url = f"{scheme}://{self._host}:{self._port}"
            # auth = (self._user, self._password)
            self._http_client = LoxoneAsyncHttpClient(
                scheme, self._host, self._port, self._user, self._password
            )
            # self._http_client = httpx.AsyncClient(
            #     auth=auth,
            #     base_url=self._http_base_url,
            #     verify=False,
            #     timeout=TIMEOUT,
            #     # event_hooks={"request": [request_hook], "response": [response_hook]},
            #     event_hooks={"response": [response_hook]},
            # )
            for interval in RETRY_INTERVALLS:
                try:
                    response = await self._http_client.loxone_get(CMD_GET_API_KEY)
                    break
                except (
                    LoxoneServiceUnAvailableError,
                    LoxoneMaxNumOfConnectionsError,
                ) as exc:
                    _LOGGER.debug(
                        f"Cannot connect. Message: {exc.response.text}. Retrying in {interval} seconds"
                    )
                    await asyncio.sleep(interval)
                    continue
                except LoxoneUnauthorisedError as exc:
                    raise exc
                except httpx.ConnectTimeout as exc:
                    _LOGGER.debug(f"Miniserver does not respond. Check host and port!")
                    raise LoxoneTimeOutError(
                        f"Miniserver does not respond. Check host and port!"
                    )
                except Exception as exc:
                    raise exc
        else:
            await self._http_client.aclose()
            raise LoxoneException("Cannot connect. Are the host/port details correct?")

        value = LoxoneResponse(response.text).value
        _LOGGER.debug("Retrieved API key data")
        # The json returned by the miniserver is invalid. It contains " and '.
        # We need to normalise it
        value_dict: dict[str, Any] = json.loads(value.replace("'", '"'))
        self._https_status = value_dict.get("httpsStatus", 0)
        self._version = value_dict.get("version", "")
        self._snr = value_dict.get("snr", "")
        self._local = value_dict.get("local", True)
        if not self._local:
            url = str(response.url)
            self._http_base_url = url.replace("/jdev/cfg/apiKey", "")

    # Step 2: Acquire the miniserver's public key
    #
    # It is convenient, whilst we have an http connection, to use it to obtain
    # the Loxone Structure File as well
    async def _get_public_key_and_structure_file(self) -> None:
        try:
            # Get the miniserver's public key
            response = await self._http_client.loxone_get(
                f"{CMD_GET_PUBLIC_KEY}",
            )
            _LOGGER.debug("Retrieved public key data")
            pk = LoxoneResponse(response.text).value
            # Loxone returns a certificate instead of a key, and the certificate is not
            # properly PEM encoded because it does not contain newlines before/after the
            # boundaries. We need to fix both problems. Proper PEM encoding requires 64
            # char line lengths throughout, but Python does not seem to insist on this.
            # If, for some reason, no certificate is returned, _public_key will be an
            # empty string.
            self._public_key = pk.replace(
                "-----BEGIN CERTIFICATE-----", "-----BEGIN PUBLIC KEY-----\n"
            ).replace("-----END CERTIFICATE-----", "\n-----END PUBLIC KEY-----")

            # The Loxone Structure File is described in a document available at
            # https://www.loxone.com/enen/kb/api/  It describes certain global
            # and external information, such as weather servers and information
            # about the miniserver itself, as well as information which does not
            # change frequently (eg categories, controls etc).

            # It is convenient to fetch it here, whilst we have an http client
            structure_file = await self._http_client.loxone_get(
                f"{LOXAPP}",
            )
            _LOGGER.debug("Retrieved structure file")
            self._structure = dict(structure_file.json())

            # The msInfo record contains static information about the
            # miniserver. It is part of the structure file.
            # Create an msInfo attribute. Dynamically add sub-attributes
            # representing each member of the msInfo dict. eg,
            # self.msInfo.msName, self.msInfo.projectName, etc
            MsInfo = namedtuple("MsInfo", self._structure["msInfo"].keys())  # type: ignore
            self._msInfo = MsInfo._make(self._structure["msInfo"].values())

        except Exception as exc:
            raise exc from None

        finally:
            # Async http client must always be closed
            await self._http_client.close()

    # Step 3: Open a websocket connection
    async def _open_websocket(self) -> None:
        scheme = "wss" if self._use_tls else "ws"
        self._url = f"{scheme}://{self._host}:{self._port}/ws/rfc6455"
        await self._open_web_socket_connection()

    # Step 4: Generate an AES256-CBC key
    # Step 5: Generate a random AES iv (16 byte)
    # Step 6: RSA Encrypt the AES key+iv with the public key
    # Step 7: Pass the encrypted session-key to the miniserver
    async def _generate_and_pass_key(self) -> None:
        # Generate an AES256-CBC key.
        self._aes_key = get_random_bytes(32)
        # Generate random 16 byte AES initialisation vector (iv)
        self._iv = get_random_bytes(16)
        # RSA Encrypt the AES key+iv with the public key
        try:
            # RSA PKCS1 has been broken for a long time. Loxone uses it anyway
            rsa_cipher = PKCS1_v1_5.new(RSA.importKey(self._public_key))
            session_key = rsa_cipher.encrypt(
                f"{self._aes_key.hex()}:{self._iv.hex()}".encode()
            )
            encrypted_session_key = b64encode(session_key).decode()
        except ValueError as exc:
            _LOGGER.error(f"Error creating RSA cipher: {exc}")
            raise LoxoneException(exc) from exc
        _LOGGER.debug("Successfully generated session key")
        # Pass the encrypted session key to the miniserver
        await self.send_ws(f"{CMD_GET_KEY_EXCHANGE}/{encrypted_session_key}")
        _LOGGER.debug("Successfully exchanged encrypted session key")

    # Step 8. Generate a random salt
    def _generate_salt(self) -> None:
        _LOGGER.debug("Generating a new salt")
        self._salt = get_random_bytes(4).hex()
        self._salt_has_expired = False

    # Step 9. Authenticate with the token (if it exists), or acquire a token
    async def _authenticate_with_token(self) -> None:
        # A Loxone token can be fairly long-lived (eg 4 weeks). So we could save
        # it to a file, and retrieve it on the next connection (if still valid).
        # But this requires filenames, loading from files etc. It is easier just
        # to ask for a new token on each connection. There might be a problem if
        # the miniserver keeps all the old, unexpired tokens, and then runs out
        # of space, but so far, so good!

        if self._token is None:
            # Once a new token is acquired, there is no need to authenticate
            # separately
            await self._acquire_token()
        else:
            raise NotImplementedError("Token loading is not implemented")
        #     # Authenticate using the existing token
        #     token_hash = self._hash_token()
        #     auth_command = f"authwithtoken/{token_hash}/{self._user}"
        #     await self._send_text_command(auth_command, encrypted=True)
