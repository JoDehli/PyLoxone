"""
Loxone constants

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

from __future__ import annotations

from typing import Final

RECONNECT_DELAY = 5  # maximum delay in seconds
RECONNECT_TRIES = 100  # number of tries to reconnect before giving up

# Loxone constants
TIMEOUT: Final = 30
KEEP_ALIVE_PERIOD: Final = 60
THROTTLE_CHECK_TOKEN_STILL_VALID: Final = (
    90  # 90 * KEEP_ALIVE_PERIOD -> 43200 sek -> 6 h
)

IV_BYTES: Final = 16
AES_KEY_SIZE: Final = 32

SALT_BYTES: Final = 16
SALT_MAX_AGE_SECONDS: Final = 60 * 60
SALT_MAX_USE_COUNT: Final = 100


# TOKEN_PERMISSION can be 2 for a 'short' lifespan token (days), or 4 for
# a longer lifespan (weeks). We ask for shorter token here. Renewing it
# is relatively easy, and the lifespan ensures that the tokens don't
# stick around for too long in the miniserver's memory if we have
# frequent restarts.
TOKEN_PERMISSION: Final = 2  # 2=web, 4=app

TOKEN_REFRESH_RETRY_COUNT: Final = 5
# token will be refreshed 1 day before its expiration date
TOKEN_REFRESH_SECONDS_BEFORE_EXPIRY: Final = (
    24 * 60 * 60
)  # 1 day --> Old. delete if new way is successful
MAX_REFRESH_DELAY: Final = 86400 # 60 * 60 * 24  # 1 day


LOXAPPPATH: Final = "/data/LoxAPP3.json"

CMD_KEEP_ALIVE: Final = "keepalive"
CMD_GET_API_KEY: Final = "/jdev/cfg/apiKey"
CMD_GET_PUBLIC_KEY: Final = "/jdev/sys/getPublicKey"
CMD_KEY_EXCHANGE: Final = "jdev/sys/keyexchange/"
CMD_GET_KEY_AND_SALT: Final = "jdev/sys/getkey2"
CMD_REQUEST_TOKEN: Final = "jdev/sys/gettoken"
CMD_REQUEST_TOKEN_JSON_WEB: Final = "jdev/sys/getjwt"
CMD_GET_KEY: Final = "jdev/sys/getkey"
CMD_AUTH_WITH_TOKEN: Final = "authwithtoken/"
CMD_REFRESH_TOKEN: Final = "jdev/sys/refreshtoken"
CMD_REFRESH_TOKEN_JSON_WEB: Final = "jdev/sys/refreshjwt/"
CMD_ENCRYPT_CMD: Final = "jdev/sys/enc/"
CMD_ENABLE_UPDATES: Final = "jdev/sps/enablebinstatusupdate"
CMD_GET_VISUAL_PASSWD: Final = "jdev/sys/getvisusalt/"

DEFAULT_TOKEN_PERSIST_NAME: Final = "lox_token.cfg"
LOX_CONFIG: Final = "loxconfig"
