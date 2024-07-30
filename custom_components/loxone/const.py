"""
Loxone constants

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

# Loxone constants
from typing import Final

from homeassistant.const import Platform

LOXONE_PLATFORMS: Final[list[Platform]] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.COVER,
    Platform.FAN,
    Platform.LIGHT,
    Platform.CLIMATE,
    Platform.ALARM_CONTROL_PANEL,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.BUTTON,
]

LOXONE_DEFAULT_PORT = 8080

TIMEOUT = 30
KEEP_ALIVE_PERIOD = 120

IV_BYTES = 16
AES_KEY_SIZE = 32

SALT_BYTES = 16
SALT_MAX_AGE_SECONDS = 60 * 60
SALT_MAX_USE_COUNT = 30

TOKEN_PERMISSION = 4  # 2=web, 4=app
TOKEN_REFRESH_RETRY_COUNT = 5
# token will be refreshed 1 day before its expiration date
TOKEN_REFRESH_SECONDS_BEFORE_EXPIRY = 24 * 60 * 60  # 1 day
#  if can't determine token expiration date, it will be refreshed after 2 days
TOKEN_REFRESH_DEFAULT_SECONDS = 2 * 24 * 60 * 60  # 2 days

LOXAPPPATH = "/data/LoxAPP3.json"

CMD_GET_PUBLIC_KEY = "jdev/sys/getPublicKey"
CMD_KEY_EXCHANGE = "jdev/sys/keyexchange/"
CMD_GET_KEY_AND_SALT = "jdev/sys/getkey2/"
CMD_REQUEST_TOKEN = "jdev/sys/gettoken/"
CMD_REQUEST_TOKEN_JSON_WEB = "jdev/sys/getjwt/"
CMD_GET_KEY = "jdev/sys/getkey"
CMD_AUTH_WITH_TOKEN = "authwithtoken/"
CMD_REFRESH_TOKEN = "jdev/sys/refreshtoken/"
CMD_REFRESH_TOKEN_JSON_WEB = "jdev/sys/refreshjwt/"
CMD_ENCRYPT_CMD = "jdev/sys/enc/"
CMD_ENABLE_UPDATES = "jdev/sps/enablebinstatusupdate"
CMD_GET_VISUAL_PASSWD = "jdev/sys/getvisusalt/"

DEFAULT_TOKEN_PERSIST_NAME = "lox_token.cfg"
ERROR_VALUE = -1
DEFAULT_PORT = 8080
DEFAULT_DELAY_SCENE = 3
DEFAULT_IP = ""

EVENT = "loxone_event"
DOMAIN = "loxone"
LOX_CONFIG = "loxconfig"

SENDDOMAIN = "loxone_send"
SECUREDSENDDOMAIN = "loxone_send_secured"
DEFAULT = ""

ATTR_UUID = "uuid"

ATTR_VALUE = "value"
ATTR_CODE = "code"
ATTR_COMMAND = "command"
ATTR_DEVICE = "device"
ATTR_AREA_CREATE = "create_areas"
DOMAIN_DEVICES = "devices"

CONF_ACTIONID = "uuidAction"
CONF_SCENE_GEN = "generate_scenes"
CONF_SCENE_GEN_DELAY = "generate_scenes_delay"
CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN = "generate_lightcontroller_subcontrols"
DEFAULT_FORCE_UPDATE = False

SUPPORT_SUN_AUTOMATION = 1024
SUPPORT_QUICK_SHADE = 2048

SERVICE_ENABLE_SUN_AUTOMATION = "enable_sun_automation"
SERVICE_DISABLE_SUN_AUTOMATION = "disable_sun_automation"
SERVICE_QUICK_SHADE = "quick_shade"

CONF_HVAC_AUTO_MODE = "hvac_auto_mode"

STATE_ON = "on"
STATE_OFF = "off"

DEFAULT_AUDIO_ZONE_V2_PLAY_STATE = -1

cfmt = """\
(                                  # start of capture group 1
%                                  # literal "%"
(?:                                # first option
(?:[-+0 #]{0,5})                   # optional flags
(?:\d+|\*)?                        # width
(?:\.(?:\d+|\*))?                  # precision
(?:h|l|ll|w|I|I32|I64)?            # size
[cCdiouxXeEfgGaAnpsSZ]             # type
) |                                # OR
%%) 
"""

# End of loxone constants
