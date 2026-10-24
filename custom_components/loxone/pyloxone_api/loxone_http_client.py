"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiohttp

from .const import TIMEOUT
from .exceptions import (LoxoneMaxNumOfConnectionsError,
                         LoxoneServiceUnAvailableError,
                         LoxoneUnauthorisedError,
                         LoxoneUnrecognizedCommandError)

_LOGGER = logging.getLogger(__name__)


class LoxoneAsyncHttpClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        scheme: str = "http",
        verify_ssl: bool = True,
        session: aiohttp.ClientSession = None,
    ):
        # Validate input parameters
        if not url:
            raise ValueError("URL cannot be empty")
        if not username:
            raise ValueError("Username cannot be empty")
        if not password:
            raise ValueError("Password cannot be empty")
        if scheme not in ("http", "https"):
            raise ValueError(f"Invalid scheme '{scheme}'. Must be 'http' or 'https'")
        if not isinstance(verify_ssl, bool):
            raise ValueError("verify_ssl must be a boolean")

        # super().__init__()
        if session is None:
            self.session = aiohttp.ClientSession()
            self._own_session = True
        # session.auth = aiohttp.BasicAuth(username, password)
        else:
            if session.closed:
                raise ValueError("Provided session is already closed")
            self.session = session
            self._own_session = False

        self.timeout = TIMEOUT
        self.base_url = f"{scheme}://{url}"
        self.scheme = scheme
        self.verify_ssl = verify_ssl
        self.username = username
        self.password = password
        self._closed = False

    @asynccontextmanager
    async def get(
        self, endpoint: str
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Yield the ``aiohttp.ClientResponse`` for ``endpoint``.

        The response is yielded inside an ``async with`` block that
        wraps the underlying ``self.session.get(...)`` call, so the
        aiohttp response and its connection-pool slot are released
        as soon as the caller exits the block — no leaks, no manual
        ``response.close()`` calls. Non-200 statuses raise before the
        yield (see :meth:`_handle_error`); the caller's body-read
        inside the ``async with`` is therefore guaranteed to be on a
        200-status response.
        """
        if self._closed:
            raise RuntimeError("HTTP client has been closed")

        if not endpoint:
            raise ValueError("Endpoint cannot be empty")

        if not endpoint.startswith("/"):
            _LOGGER.warning(f"Endpoint '{endpoint}' should start with '/'")
            endpoint = f"/{endpoint}"

        url = f"{self.base_url}{endpoint}"
        _LOGGER.debug(f"Making GET request to: {url}")
        request_kwargs = {
            "auth": aiohttp.BasicAuth(self.username, self.password, encoding="utf-8"),
            "timeout": aiohttp.ClientTimeout(total=self.timeout),
        }
        if self.scheme == "https":
            request_kwargs["ssl"] = self.verify_ssl

        try:
            # ``async with`` releases the aiohttp response and its
            # connection-pool slot on block exit. The caller reads
            # ``response.content`` inside the block and may also use
            # ``response.url`` (e.g. for the Cloud-DNS redirect
            # detection in ``connection.py``).
            async with self.session.get(url, **request_kwargs) as response:
                if response.status != 200:
                    await self._handle_error(response)
                yield response

        except asyncio.TimeoutError as err:
            # Transient: the caller retries and reports it once.
            _LOGGER.debug("Timeout error for %s", url)
            raise TimeoutError(
                f"Request to {url} timed out after {self.timeout} seconds"
            ) from err

        # The previous implementation listed seven specific
        # ``aiohttp.ClientError`` subclasses (ClientConnectionError,
        # ClientConnectorError, ClientSSLError, ClientProxyConnectionError,
        # ServerDisconnectedError, ClientPayloadError,
        # ClientResponseError) — all of which are subclasses of
        # ``ClientError`` and produced the same ERROR-log + re-raise
        # pattern. They are subsumed by the single ``ClientError``
        # handler below.
        except aiohttp.ClientError as err:
            # Transient: the caller retries and reports it once.
            _LOGGER.debug("HTTP client error for %s: %s", url, err)
            raise ConnectionError(
                f"Failed to connect to Loxone Miniserver at {url}: {err}"
            ) from err

        except (
            LoxoneUnauthorisedError,
            LoxoneUnrecognizedCommandError,
            LoxoneServiceUnAvailableError,
            LoxoneMaxNumOfConnectionsError,
        ):
            # Re-raise Loxone-specific errors without wrapping — these
            # are raised inside ``_handle_error`` and are meaningful
            # to the caller (e.g. supervisor reload on
            # ``LoxoneUnauthorisedError``).
            raise

        except Exception as err:
            _LOGGER.exception(f"Unexpected error during GET request to {url}")
            raise RuntimeError(
                f"Unexpected error during HTTP request: {err}"
            ) from err

    async def close(self):
        if self._closed:
            _LOGGER.warning("HTTP client is already closed")
            return

        try:
            if self._own_session and not self.session.closed:
                await self.session.close()
            self._closed = True
            _LOGGER.debug("HTTP client closed successfully")
        except Exception as err:
            _LOGGER.error(f"Error closing HTTP client: {err}")
            self._closed = True
            raise RuntimeError(f"Failed to close HTTP session: {err}") from err

    @staticmethod
    async def _handle_error(response):
        content = None

        try:
            # Try to read content with timeout protection
            try:
                content = await asyncio.wait_for(response.content.read(), timeout=5.0)
                content = content.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout reading error response content")
                content = "<timeout reading response>"
            except UnicodeDecodeError as err:
                _LOGGER.warning(f"Failed to decode response content: {err}")
                content = "<binary content>"
            except Exception as err:
                _LOGGER.warning(f"Error reading response content: {err}")
                content = f"<error reading content: {err}>"

        except Exception as err:
            _LOGGER.error(f"Critical error handling response: {err}")
            content = "<unavailable>"

        # Handle specific HTTP status codes
        if response.status == 400:
            _LOGGER.error(f"Bad Request (400): {content}")
            raise ValueError(f"Bad request to Loxone Miniserver: {content}")

        elif response.status == 401:
            _LOGGER.error(f"Unauthorized (401): {content}")
            err = LoxoneUnauthorisedError(f"Unauthorized: {content}")
            err.response = response
            raise err

        elif response.status == 403:
            _LOGGER.error(f"Forbidden (403): {content}")
            raise PermissionError(f"Access forbidden: {content}")

        elif response.status == 404:
            _LOGGER.error(f"Not Found (404): {content}")
            err = LoxoneUnrecognizedCommandError(f"Unrecognized command: {content}")
            err.response = response
            raise err

        elif response.status == 408:
            _LOGGER.error(f"Request Timeout (408): {content}")
            raise TimeoutError(f"Request timeout: {content}")

        elif response.status == 429:
            _LOGGER.error(f"Too Many Requests (429): {content}")
            raise RuntimeError(f"Rate limit exceeded: {content}")

        elif response.status == 500:
            _LOGGER.error(f"Internal Server Error (500): {content}")
            raise RuntimeError(f"Miniserver internal error: {content}")

        elif response.status == 502:
            _LOGGER.error(f"Bad Gateway (502): {content}")
            raise ConnectionError(f"Bad gateway: {content}")

        elif response.status == 503:
            _LOGGER.error(f"Service Unavailable (503): {content}")
            err = LoxoneServiceUnAvailableError(
                f"Service Unavailable; The Miniserver is restarting and not ready for requests: {content}"
            )
            err.response = response
            raise err

        elif response.status == 504:
            _LOGGER.error(f"Gateway Timeout (504): {content}")
            raise TimeoutError(f"Gateway timeout: {content}")

        elif response.status == 901:
            _LOGGER.error(f"Max Connections (901): {content}")
            err = LoxoneMaxNumOfConnectionsError(
                f"Maximum number of allowed concurrent connections reached: {content}"
            )
            err.response = response
            raise err

        else:
            # Generic error for any other status code
            _LOGGER.error(f"HTTP Error {response.status}: {content}")
            raise RuntimeError(f"HTTP error {response.status}: {content}")

    # def __enter__(self):
    #     raise RuntimeError("Use 'async with' to create an AsyncHttpClient instance")
    #
    # def __exit__(self, exc_type, exc_value, traceback):
    #     pass
