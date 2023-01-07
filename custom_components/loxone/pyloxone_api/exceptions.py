""" Loxone exceptions"""


class LoxoneException(Exception):
    """Base class for all Loxone Exceptions"""


class LoxoneOutOfServiceException(Exception):
    """Raised when the Miniserver goes down for a reboot"""


class LoxoneHTTPStatusError(LoxoneException):
    """An exception indicating an unusual http response from the miniserver"""


class LoxoneRequestError(LoxoneException):
    """An exception raised during an http request"""


class LoxoneUnauthorisedError(LoxoneRequestError):
    """Unauthorised web request. Incorrect credentials"""


class LoxoneCommandError(LoxoneException):
    """An exception raised when a command is sent to the miniserver"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
