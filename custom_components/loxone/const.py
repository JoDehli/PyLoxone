"""
Loxone constants

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
LOXONE_PLATFORMS = [
    "sensor",
    "switch",
    "cover",
    "light",
    "climate",
    "scene",
    "alarm_control_panel",
]

DOMAIN = "loxone"
SENDDOMAIN = "loxone_send"
SECUREDSENDDOMAIN = "loxone_send_secured"
EVENT = 'loxone_event'
DEFAULT = ""
DEFAULT_PORT = 8080
DEFAULT_IP = ""

ATTR_UUID = "uuid"

ATTR_UUID = "uuid"
ATTR_VALUE = "value"
ATTR_CODE = "code"
ATTR_COMMAND = "command"
DOMAIN_DEVICES = "devices"

CONF_ACTIONID = "uuidAction"
CONF_SCENE_GEN = "generate_scenes"
CONF_SCENE_GEN_DELAY = "generate_scenes_delay"
CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN = "generate_lightcontroller_subcontrols"
DEFAULT_FORCE_UPDATE = False

SUPPORT_SET_POSITION = 4
SUPPORT_STOP = 8
SUPPORT_OPEN_TILT = 16
SUPPORT_CLOSE_TILT = 32
SUPPORT_STOP_TILT = 64
SUPPORT_SET_TILT_POSITION = 128
DEFAULT_DELAY_SCENE = 3

CONF_HVAC_AUTO_MODE = "hvac_auto_mode"

STATE_ON = "on"
STATE_OFF = "off"


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
