"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import asyncio
import logging
import warnings

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
        self.username = username
        self.password = password
        self._closed = False

    async def get(self, endpoint):
        if self._closed:
            raise RuntimeError("HTTP client has been closed")

        if not endpoint:
            raise ValueError("Endpoint cannot be empty")

        if not endpoint.startswith("/"):
            _LOGGER.warning(f"Endpoint '{endpoint}' should start with '/'")
            endpoint = f"/{endpoint}"

        url = f"{self.base_url}{endpoint}"
        response = None

        try:
            _LOGGER.debug(f"Making GET request to: {url}")
            response = await self.session.get(
                url,
                auth=aiohttp.BasicAuth(self.username, self.password),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )

            if response.status != 200:
                await self._handle_error(response)

            return response

        except aiohttp.ClientConnectionError as err:
            _LOGGER.error(f"Connection error to {url}: {err}")
            raise ConnectionError(
                f"Failed to connect to Loxone Miniserver at {url}: {err}"
            ) from err

        except aiohttp.ClientConnectorError as err:
            _LOGGER.error(f"Connector error to {url}: {err}")
            raise ConnectionError(f"Cannot resolve or connect to {url}: {err}") from err

        except asyncio.TimeoutError as err:
            _LOGGER.error(f"Timeout error for {url}")
            raise TimeoutError(
                f"Request to {url} timed out after {self.timeout} seconds"
            ) from err

        except aiohttp.ClientSSLError as err:
            _LOGGER.error(f"SSL error for {url}: {err}")
            raise ConnectionError(f"SSL/TLS error connecting to {url}: {err}") from err

        except aiohttp.ClientProxyConnectionError as err:
            _LOGGER.error(f"Proxy connection error for {url}: {err}")
            raise ConnectionError(f"Proxy connection error: {err}") from err

        except aiohttp.ServerDisconnectedError as err:
            _LOGGER.error(f"Server disconnected for {url}: {err}")
            raise ConnectionError(f"Server disconnected unexpectedly: {err}") from err

        except aiohttp.ClientPayloadError as err:
            _LOGGER.error(f"Payload error for {url}: {err}")
            raise ValueError(f"Invalid response payload from server: {err}") from err

        except aiohttp.ClientResponseError as err:
            _LOGGER.error(f"Response error for {url}: {err}")
            raise RuntimeError(f"HTTP response error: {err}") from err

        except aiohttp.ClientError as err:
            _LOGGER.error(f"Client error for {url}: {err}")
            raise RuntimeError(f"HTTP client error: {err}") from err

        except (
            LoxoneUnauthorisedError,
            LoxoneUnrecognizedCommandError,
            LoxoneServiceUnAvailableError,
            LoxoneMaxNumOfConnectionsError,
        ):
            # Re-raise Loxone-specific errors without wrapping
            raise

        except Exception as err:
            _LOGGER.exception(f"Unexpected error during GET request to {url}")
            raise RuntimeError(f"Unexpected error during HTTP request: {err}") from err

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
