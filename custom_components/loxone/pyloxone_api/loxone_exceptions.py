class LoxoneException(Exception):
    """Base class for all Loxone Exceptions"""

    response = None


class LoxoneTimeOutError(LoxoneException):
    """An exception indicating an unusual http response from the miniserver"""


class LoxoneHTTPStatusError(LoxoneException):
    """An exception indicating an unusual http response from the miniserver"""


class LoxoneRequestError(LoxoneException):
    """An exception raised during an http request"""


class LoxoneUnauthorisedError(LoxoneRequestError):
    """Unauthorised web request. Incorrect credentials"""


class LoxoneServiceUnAvailableError(LoxoneRequestError):
    """Service Unavailable; The Miniserver is restarting and not ready for requests"""


class LoxoneMaxNumOfConnectionsError(LoxoneRequestError):
    """Maximum number of allowed concurrent connections reached"""


class LoxoneUnrecognizedCommandError(LoxoneRequestError):
    """Unrecognized command"""
