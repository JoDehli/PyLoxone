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
]

LOXONE_DEFAULT_PORT = 8080

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

CONF_SENSOR_DEVICE_CLASS_MAP: str = "sensor_device_class_map"
"""Config entry option key for sensor device class mapping."""

MAPPABLE_DEVICE_CLASSES: list[tuple[str, str]] = [
    ("humidity", "Humidity (%)"),
    ("battery", "Battery (%)"),
    ("carbon_dioxide", "Carbon Dioxide (ppm)"),
    ("illuminance", "Illuminance (lx)"),
    ("sound_pressure", "Sound Pressure (dB)"),
    ("aqi", "Air Quality Index"),
    ("pm25", "PM2.5"),
    ("pm10", "PM10"),
    ("pm1", "PM1"),
    ("volatile_organic_compounds", "VOC"),
]
"""Device classes users can map sensors to via the options flow."""

SENSOR_CLASS_RULES: list[dict] = [
    {
        "device_class": "temperature",
        "matchers": [
            {"unit": ["°C", "°F"]},
        ],
    },
    {
        "device_class": "carbon_dioxide",
        "matchers": [
            {"unit": ["ppm"]},
        ],
    },
    {
        "device_class": "illuminance",
        "matchers": [
            {"unit": ["lx", "Lx", "lux"]},
        ],
    },
    {
        "device_class": "wind_speed",
        "matchers": [
            {"unit": ["km/h"]},
        ],
    },
    {
        "device_class": "power",
        "matchers": [
            {"unit": ["W", "kW"]},
        ],
    },
    {
        "device_class": "energy",
        "matchers": [
            {"unit": ["kWh", "Wh", "MWh"]},
        ],
    },
    {
        "device_class": "battery",
        "matchers": [
            {"unit": ["%"], "name": ["batt", "akku"]},
        ],
    },
    {
        "device_class": "humidity",
        "matchers": [
            {"unit": ["%"], "category": ["vlhkost", "humidity", "feucht", "humidit", "luftfukt"]},
            {"unit": ["%"], "name": ["vlhkost", "humidity", "feucht", "humidité", "luftfukt"]},
        ],
    },
]
"""Rule-based device class detection rules.

Each rule defines conditions (unit, category, name) that identify a specific
device_class. Rules are checked in order; first match wins. Conditions are
AND within a matcher, OR between matchers in the same rule.
"""

UNAMBIGUOUS_UNITS: set[str] = {
    unit
    for rule in SENSOR_CLASS_RULES
    for m in rule["matchers"]
    if set(m.keys()) == {"unit"}
    for unit in m.get("unit", [])
}
"""Unit strings that unambiguously identify a device class (no user mapping needed)."""
