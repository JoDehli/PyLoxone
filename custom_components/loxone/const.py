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
]

LOXONE_DEFAULT_PORT = 80

ERROR_VALUE = -1
DEFAULT_PORT = 80
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

SERVICE_ENABLE_SUN_AUTOMATION = "enable_sun_automation"
SERVICE_DISABLE_SUN_AUTOMATION = "disable_sun_automation"
SERVICE_QUICK_SHADE = "quick_shade"

CONF_HVAC_AUTO_MODE = "hvac_auto_mode"

# Physical hardware inventory and mapping.
CONF_HARDWARE_ENABLED = "hardware_enabled"
CONF_HARDWARE_FAST_POLL_INTERVAL = "hardware_fast_poll_interval"
CONF_HARDWARE_INVENTORY_INTERVAL = "hardware_inventory_interval"
CONF_HARDWARE_BATTERY_INTERVAL = "hardware_battery_interval"
CONF_HARDWARE_MAPPINGS = "hardware_mappings"
DEFAULT_HARDWARE_ENABLED = True
DEFAULT_HARDWARE_FAST_POLL_INTERVAL = 2
DEFAULT_HARDWARE_INVENTORY_INTERVAL = 30
DEFAULT_HARDWARE_BATTERY_INTERVAL = 15

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
