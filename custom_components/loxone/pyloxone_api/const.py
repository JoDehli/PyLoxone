"""
Loxone constants


"""
from typing import Final

TIMEOUT: Final = 30

# PERMISSION can be 2 for a 'short' lifespan token (days), or 4 for
# a longer lifespan (weeks). We ask for shorter token here. Renewing it
# is relatively easy, and the lifespan ensures that the tokens don't
# stick around for too long in the miniserver's memory if we have
# frequent restarts.
PERMISSION: Final = 2

# RETRY_INTERVALLS: Final = [10, 20, 30, 60, 60, 120, 240]
RETRY_INTERVALLS: Final = [1, 5]

CMD_API: Final = "/jdev/cfg/api"
CMD_GET_API_KEY: Final = "/jdev/cfg/apiKey"
CMD_GET_KEY: Final = "jdev/sys/getkey"
CMD_GET_KEY2: Final = "jdev/sys/getkey2"
CMD_GET_KEY_EXCHANGE: Final = "jdev/sys/keyexchange"
CMD_GET_JWT: Final = "jdev/sys/getjwt"
CMD_GET_PUBLIC_KEY: Final = "/jdev/sys/getPublicKey"
LOXAPP: Final = "/data/LoxAPP3.json"
CMD_ENABLE_UPDATES: Final = "jdev/sps/enablebinstatusupdate"
