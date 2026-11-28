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
    Platform.SCENE,
    Platform.SELECT,
    Platform.TEXT,
]

LOXONE_DEFAULT_PORT = 8080

ERROR_VALUE = -1
DEFAULT_PORT = 8080
DEFAULT_VERIFY_SSL = True
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
CLIMATE_EVENT = "loxone_climate"

# Climate preset names (translatable)
PRESET_SCHEDULE = "schedule"
PRESET_PAUSED_WINDOW = "paused_door_window"

CONF_ACTIONID = "uuidAction"
CONF_SCENE_GEN = "generate_scenes"
CONF_SCENE_GEN_DELAY = "generate_scenes_delay"
CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN = "generate_lightcontroller_subcontrols"
CONF_VERIFY_SSL = "verify_ssl"
DEFAULT_FORCE_UPDATE = False

SUPPORT_SUN_AUTOMATION = 1024
SUPPORT_QUICK_SHADE = 2048
SUPPORT_SLIGHTLY_OPEN = 4096

SERVICE_ENABLE_SUN_AUTOMATION = "enable_sun_automation"
SERVICE_DISABLE_SUN_AUTOMATION = "disable_sun_automation"
SERVICE_QUICK_SHADE = "quick_shade"
SERVICE_WINDOW_SLIGHTLY_OPEN = "window_slightly_open"
SERVICE_REFRESH_TOKEN = "refresh_token"

CONF_HVAC_AUTO_MODE = "hvac_auto_mode"

# How a single target temperature set on a room controller V2 in automatic
# mode is sent to the Miniserver:
# - comfort_offset: ``setComfortModeTemp`` (the previous behaviour, default).
#   Adjusts the comfort temperature until the scheduled comfort period ends.
# - manual_override: ``override/3/{until}/{temp}``, the manual override timer
#   ("fixed setpoint") that third-party voice bridges such as 1Home use.
CONF_IRC_SETPOINT_MODE = "irc_setpoint_mode"
IRC_SETPOINT_COMFORT_OFFSET = "comfort_offset"
IRC_SETPOINT_MANUAL_OVERRIDE = "manual_override"
DEFAULT_IRC_SETPOINT_MODE = IRC_SETPOINT_COMFORT_OFFSET
# Length of the manual override in hours. The Miniserver needs an end time
# for the override to start, so the minimum is half an hour.
CONF_IRC_OVERRIDE_HOURS = "irc_override_hours"
DEFAULT_IRC_OVERRIDE_HOURS = 4

STATE_ON = "on"
STATE_OFF = "off"

DEFAULT_AUDIO_ZONE_V2_PLAY_STATE = -1

THROTTLE_KEEP_ALIVE_TIME = 60

r"""\
cfmt description
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

cfmt = r"(%(?:(?:[-+0 #]{0,5})(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:h|l|ll|w|I|I32|I64)?[cCdiouxXeEfgGaAnpsSZ])|%%)"
