"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import logging
import warnings
import httpx

from .const import TIMEOUT
from .exceptions import (LoxoneMaxNumOfConnectionsError,
                         LoxoneServiceUnAvailableError,
                         LoxoneUnauthorisedError,
                         LoxoneUnrecognizedCommandError)

_LOGGER = logging.getLogger(__name__)

# Filter out the specific warning
warnings.filterwarnings(
    "ignore",
    message="Detected blocking call to load_verify_locations",
    module="httpx._config"
)
import aiohttp

class LoxoneAsyncHttpClient:
    def __init__(
        self, host: str, port: int, username: str, password: str, scheme: str = "http",
            session: aiohttp.ClientSession = None
    ):
        #super().__init__()
        if session is None:
            self.session = aiohttp.ClientSession()
        #session.auth = aiohttp.BasicAuth(username, password)
        else:
            self.session = session

        self.timeout = TIMEOUT
        self.base_url = f"{scheme}://{host}:{port}"
        self.username = username
        self.password = password

    async def get(self, endpoint):
        url = f"{self.base_url}{endpoint}"
        response = await self.session.get(url, auth=aiohttp.BasicAuth(self.username, self.password))
        if response.status != 200:
            await self._handle_error(response)
        return response

        # async with self.session.get(url) as response:
        #     if response.status != 200:
        #         await self._handle_error(response)
        #     data = await response.content.read()
        #     return response

        #response = await self.session.get(url)
        #await self._handle_error(response)


    async def close(self):
        await self.session.aclose()

    @staticmethod
    async def _handle_error(response):
        if response.status == 401:
            content = await response.content.read()
            err = LoxoneUnauthorisedError(f"Unauthorized: {content}")
            err.response = response
            raise err
        elif response.status == 404:
            content = await response.content.read()
            err = LoxoneUnrecognizedCommandError(f"Unrecognized command: {content}")
            err.response = response
            raise err
        elif response.status == 503:
            content = await response.content.read()
            err = LoxoneServiceUnAvailableError(
                f"Service Unavailable; The Miniserver is restarting and not ready for requests: {content}"
            )
            err.response = response
            raise err
        elif response.status == 901:
            content = await response.content.read()
            err = LoxoneMaxNumOfConnectionsError(
                f"Maximum number of allowed concurrent connections reached: {content}"
            )
            err.response = response
            raise err

    # def __enter__(self):
    #     raise RuntimeError("Use 'async with' to create an AsyncHttpClient instance")
    #
    # def __exit__(self, exc_type, exc_value, traceback):
    #     pass
