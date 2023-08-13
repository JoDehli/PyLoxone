import logging

import httpx

from loxone_exceptions import (
    LoxoneMaxNumOfConnectionsError,
    LoxoneServiceUnAvailableError,
    LoxoneUnauthorisedError,
    LoxoneUnrecognizedCommandError,
)

_LOGGER = logging.getLogger(__name__)


# # Define an event hook function
# async def request_hook(request, **kwargs):
#     _LOGGER.debug(f"Request being sent: {request.method} {request.url}")


# async def response_hook(response: httpx.Response, **kwargs):
#     _LOGGER.debug(f"Response received: {response.status_code} {response.url}")
#     if response.status_code == 401:
#         content = await response.aread()
#         err = LoxoneUnauthorisedError(f"Unauthorized: {content}")
#         err.response = response
#         raise err
#     if response.status_code == 503:
#         content = await response.aread()
#         err = LoxoneServiceUnAvailableError(
#             f"Service Unavailable; The Miniserver is restarting and not ready for requests: {content}"
#         )
#         err.response = response
#         raise err
#     if response.status_code == 901:
#         content = await response.aread()
#         err = LoxoneMaxNumOfConnectionsError(
#             f"Maximum number of allowed concurrent connections reached: {content}"
#         )
#         err.response = response
#         raise err
#     if response.status_code == 404:
#         content = await response.aread()
#         err = LoxoneUnrecognizedCommandError(f"Unrecognized command: {content}")
#         err.response = response
#         raise err


class LoxoneAsyncHttpClient(httpx.AsyncClient):
    def __init__(self, scheme, host, port, username, password):
        super().__init__(auth=(username, password))
        self.base_url = f"{scheme}://{host}:{port}"
        self.username = username
        self.password = password

    async def loxone_get(self, endpoint):
        url = f"{self.base_url}{endpoint}"
        response = await self.get(url)
        await self._handle_error(response)
        return response

    async def close(self):
        await self.aclose()

    @staticmethod
    async def _handle_error(response):
        if response.status_code == 401:
            content = await response.aread()
            err = LoxoneUnauthorisedError(f"Unauthorized: {content}")
            err.response = response
            raise err
        elif response.status_code == 404:
            content = await response.aread()
            err = LoxoneUnrecognizedCommandError(f"Unrecognized command: {content}")
            err.response = response
            raise err
        elif response.status_code == 503:
            content = await response.aread()
            err = LoxoneServiceUnAvailableError(
                f"Service Unavailable; The Miniserver is restarting and not ready for requests: {content}"
            )
            err.response = response
            raise err
        elif response.status_code == 901:
            content = await response.aread()
            err = LoxoneMaxNumOfConnectionsError(
                f"Maximum number of allowed concurrent connections reached: {content}"
            )
            err.response = response
            raise err

    def __enter__(self):
        raise RuntimeError("Use 'async with' to create an AsyncHttpClient instance")

    def __exit__(self, exc_type, exc_value, traceback):
        pass
