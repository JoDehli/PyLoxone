"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""


class LoxoneException(Exception):
    """Base class for all Loxone Exceptions"""

    response = None


class LoxoneOutOfServiceException(Exception):
    """Raised when the Miniserver goes down for a reboot"""


class LoxoneConnectionClosedOk(Exception):
    """Raised when websocket ClosedOk received. Should we reconnect?"""


class LoxoneConnectionError(Exception):
    """Raised the network connection is interrupted"""


class LoxoneHTTPStatusError(LoxoneException):
    """An exception indicating an unusual http response from the miniserver"""


class LoxoneRequestError(LoxoneException):
    """An exception raised during an http request"""


class LoxoneUnauthorisedError(LoxoneRequestError):
    """Unauthorised web request. Incorrect credentials"""


class LoxoneTokenError(LoxoneRequestError):
    """Unauthorised web request. Incorrect credentials"""


class LoxoneCommandError(LoxoneException):
    """An exception raised when a command is sent to the miniserver"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class LoxoneTimeOutError(LoxoneException):
    """An exception indicating an unusual http response from the miniserver"""


class LoxoneServiceUnAvailableError(LoxoneRequestError):
    """Service Unavailable; The Miniserver is restarting and not ready for requests"""


class LoxoneMaxNumOfConnectionsError(LoxoneRequestError):
    """Maximum number of allowed concurrent connections reached"""


class LoxoneUnrecognizedCommandError(LoxoneRequestError):
    """Unrecognized command"""


class ConnectionFailure(Exception):
    """Error during connection."""

    pass


class UnauthorizedError(ConnectionFailure):
    """Error from ms.channel.unauthorized event."""

    pass


class ResponseError(Exception):
    """Error in response."""

    pass


class HttpApiError(Exception):
    """Error using HTTP API."""

    pass


class MessageError(Exception):
    """Error from ms.error event."""

    pass
