"""
Loxone constants

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

from __future__ import annotations

from typing import Final

RECONNECT_DELAY = 5  # base delay in seconds for the exponential backoff
RECONNECT_TRIES = 5  # number of tries before giving up on a bootstrap GET
MAX_RECONNECT_DELAY = 60  # cap on the per-attempt sleep, in seconds

# Loxone constants
MAX_WEBSOCKET_MESSAGE_SIZE: Final = 5 * 1024 * 1024  # 5 megabytes = 5,242,880 bytes
# Size of the binary frame header (``WsBinHdr``): cBinType, cIdentifier,
# cInfo, cReserved and a 32-bit little-endian payload length.
MESSAGE_HEADER_SIZE: Final = 8
WEBSOCKET_CLOSE_TIMEOUT: Final = 10  # seconds to wait for a clean close
# Seconds without any inbound frame after which the websocket is considered
# stale. The Miniserver sends a KEEPALIVE roughly every KEEP_ALIVE_PERIOD
# (30) seconds, so this equals three missed keepalives. Needed because the
# ``websockets`` library's own ping/pong liveness check is disabled (see
# ``LoxoneConnection._build_websocket_options``) — the Loxone keepalive is
# the single liveness channel, and a half-open TCP connection (roaming,
# pulled cable, frozen Miniserver) would otherwise only be noticed when the
# TCP retransmit timeout fires, i.e. minutes later.
WEBSOCKET_READ_TIMEOUT: Final = 90
DELAY_CHECK_TOKEN_REFRESH: Final = 20
TIMEOUT: Final = 30
KEEP_ALIVE_PERIOD: Final = 30
THROTTLE_CHECK_TOKEN_STILL_VALID: Final = (
    90  # 90 * KEEP_ALIVE_PERIOD -> 43200 sek -> 6 h
)

IV_BYTES: Final = 16
AES_KEY_SIZE: Final = 32

SALT_BYTES: Final = 16
SALT_MAX_AGE_SECONDS: Final = 60 * 60
SALT_MAX_USE_COUNT: Final = 100
# Seconds a secure command may wait for its getvisusalt reply. Older
# commands are dropped instead of being sent late (e.g. a gate opening
# minutes after the user gave up).
SECURED_COMMAND_TIMEOUT: Final = 30


# TOKEN_PERMISSION can be 2 for a 'short' lifespan token (days), or 4 for
# a longer lifespan (weeks). We ask for shorter token here. Renewing it
# is relatively easy, and the lifespan ensures that the tokens don't
# stick around for too long in the miniserver's memory if we have
# frequent restarts.
TOKEN_PERMISSION: Final = 2  # 2=web, 4=app

TOKEN_REFRESH_RETRY_COUNT: Final = 5
TOKEN_REFRESH_MAX_FAILURES: Final = 10  # consecutive failures before raising
# token will be refreshed 1 day before its expiration date
TOKEN_REFRESH_SECONDS_BEFORE_EXPIRY: Final = (
    24 * 60 * 60
)  # 1 day --> Old. delete if new way is successful
MAX_REFRESH_DELAY: Final = 86400  # 60 * 60 * 24  # 1 day


LOXAPPPATH: Final = "/data/LoxAPP3.json"

CMD_KEEP_ALIVE: Final = "keepalive"
CMD_GET_API_KEY: Final = "/jdev/cfg/apiKey"
CMD_GET_PUBLIC_KEY: Final = "/jdev/sys/getPublicKey"
CMD_KEY_EXCHANGE: Final = "jdev/sys/keyexchange/"
CMD_GET_KEY: Final = "jdev/sys/getkey"
CMD_GET_KEY_AND_SALT: Final = "jdev/sys/getkey2"
CMD_REQUEST_TOKEN: Final = "jdev/sys/gettoken"
CMD_REQUEST_TOKEN_JSON_WEB: Final = "jdev/sys/getjwt"
CMD_AUTH_WITH_TOKEN: Final = "authwithtoken/"
CMD_REFRESH_TOKEN: Final = "jdev/sys/refreshtoken/"
CMD_REFRESH_TOKEN_JSON_WEB: Final = "jdev/sys/refreshjwt/"
CMD_KILL_TOKEN: Final = "jdev/sys/killtoken"
CMD_ENCRYPT_CMD: Final = "jdev/sys/enc/"
CMD_ENABLE_UPDATES: Final = "jdev/sps/enablebinstatusupdate"
CMD_GET_VISUAL_PASSWD: Final = "jdev/sys/getvisusalt/"

# LL envelope codes that mean "credentials rejected". The
# Miniserver returns 401 for the standard username/password
# auth path and 4003 (legacy) for older Miniservers / firmware
# variants. Any other non-200 code is logged at WARNING and the
# auth flow continues — those are usually transient.
LLRSP_UNAUTHORISED_CODES: Final = frozenset({401, 4003})

DEFAULT_TOKEN_PERSIST_NAME: Final = "lox_token.cfg"
LOX_CONFIG: Final = "loxconfig"
