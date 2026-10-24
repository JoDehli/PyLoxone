"""
Helper functions

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/loxone/
"""

import json
import re

from .const import DOMAIN, cfmt

_COLOR_RE = re.compile(r"^\s*(hsv|temp)\s*\(([^()]*)\)\s*$")


def parse_lox_json(text):
    """Parse a JSON text state (e.g. ``moodList``, ``activeMoods``).

    Miniserver data is never evaluated as Python code. Raises
    ``ValueError`` if ``text`` is not valid JSON.
    """
    return json.loads(text)


def parse_lox_color(text: str) -> tuple[str, list[int | float]]:
    """Parse ``hsv(h,s,v)`` / ``temp(brightness,kelvin)`` color states.

    Returns the kind (``"hsv"`` or ``"temp"``) and the numbers.
    Raises ``ValueError`` for anything else.
    """
    match = _COLOR_RE.match(text)
    if match is None:
        raise ValueError(f"Not a Loxone color: {text!r}")
    numbers = json.loads(f"[{match.group(2)}]")
    if not numbers or not all(
        isinstance(n, (int, float)) and not isinstance(n, bool) for n in numbers
    ):
        raise ValueError(f"Not a Loxone color: {text!r}")
    return match.group(1), numbers


LOCKED_BY = {1: "visualisation", 2: "logic"}


def parse_control_lock(value) -> tuple[int, str]:
    """Decode a control's ``jLocked`` state into ``(locked, reason)``.

    Structure file v16, "Locking controls": a text state holding JSON
    ``{"locked": 0|1|2, "reason": "..."}`` (0 = not locked, 1 = by the
    visualisation, 2 = by logic); an empty string means not locked. A
    plain number is accepted as the ``locked`` value. Anything unreadable
    reads as not locked, so a parse problem never blocks a control.
    """
    if value is None or value == "":
        return 0, ""
    if isinstance(value, (int, float)):
        return (int(value) if int(value) in (0, 1, 2) else 0), ""
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except ValueError:
            return 0, ""
        if isinstance(data, dict):
            try:
                locked = int(data.get("locked", 0))
            except (TypeError, ValueError):
                locked = 0
            reason = data.get("reason")
            return (locked if locked in (0, 1, 2) else 0), (reason if isinstance(reason, str) else "")
        if isinstance(data, (int, float)):
            return parse_control_lock(data)
    return 0, ""

# Initialize a device registry
device_registry = {}


def get_or_create_device(device_uuid, device_name, device_type, device_room):
    if device_uuid not in device_registry:
        device_registry[device_uuid] = {
            "identifiers": {(DOMAIN, device_uuid)},
            "name": device_name,
            "manufacturer": "Loxone",
            "model": device_type,
            "suggested_area": device_room,
        }
    return device_registry[device_uuid]


def map_range(value, in_min, in_max, out_min, out_max):
    return out_min + (((value - in_min) / (in_max - in_min)) * (out_max - out_min))


def hass_to_lox(level):
    """Convert the given HASS light level (0-255) to Loxone (0.0-100.0)."""
    return (level * 100.0) / 255.0


def lox_to_hass(lox_val):
    """Convert the given Loxone (0.0-100.0) light level to HASS (0-255)."""
    return (lox_val / 100.0) * 255.0


def lox2lox_mapped(x, min_v, max_v):
    if x <= min_v:
        return 0
    if x >= max_v:
        return max_v
    return x


def lox2hass_mapped(x, min_v, max_v):
    if x <= min_v:
        return 0
    if x >= max_v:
        return lox_to_hass(max_v)
    return lox_to_hass(x)


# def to_hass_color_temp(temp: float):
#     """Linear interpolation between Loxone values from 2700 to 6500"""
#     return np.interp(temp, [2700, 6500], [500, 153])
#
#
# def to_loxone_color_temp(temp: float):
#     """Linear interpolation between HASS values from 153 to 500"""
#     return np.interp(temp, [153, 500], [6500, 2700])


def to_hass_color_temp(temp: float):
    """Linear interpolation between Loxone values from 2700 to 6500"""
    if temp <= 2700:
        return 500
    if temp >= 6500:
        return 153
    return 500 + (temp - 2700) * (153 - 500) / (6500 - 2700)


def to_loxone_color_temp(temp: float):
    """Linear interpolation between HASS values from 153 to 500"""
    if temp <= 153:
        return 6500
    if temp >= 500:
        return 2700
    return 6500 + (temp - 153) * (2700 - 6500) / (500 - 153)


def get_room_name_from_room_uuid(lox_config: dict, room_uuid: str):
    if "rooms" in lox_config:
        if room_uuid in lox_config["rooms"]:
            return lox_config["rooms"][room_uuid]["name"]

    return ""


def get_cat_name_from_cat_uuid(lox_config: dict, cat_uuid: str):
    if "cats" in lox_config:
        if cat_uuid in lox_config["cats"]:
            return lox_config["cats"][cat_uuid]["name"]
    return ""


def add_room_and_cat_to_value_values(loxconfig: dict, sensor: dict):
    sensor.update(
        {
            "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
            "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
        }
    )
    return sensor


def get_miniserver_type(t):
    if t == 0:
        return "Miniserver (Gen 1)"
    elif t == 1:
        return "Miniserver Go (Gen 1)"
    elif t == 2:
        return "Miniserver (Gen 2)"
    elif t == 3:
        return "Miniserver Go (Gen 2)"
    elif t == 4:
        return "Miniserver Compact"
    return "Unknown type"


def get_all(json_data, name):
    controls = []
    if isinstance(name, list):
        for c in json_data["controls"].keys():
            if json_data["controls"][c]["type"] in name:
                controls.append(json_data["controls"][c])
    else:
        for c in json_data["controls"].keys():
            if json_data["controls"][c]["type"] == name:
                controls.append(json_data["controls"][c])
    return controls


def clean_unit(lox_format):
    """Extract the unit string from a Loxone format specifier like '%.1f °C'."""
    search = re.search(cfmt, lox_format, flags=re.X)
    if search:
        unit = lox_format.replace(search.group(0).strip(), "").strip()
        if unit == "%%":
            unit = "%"
        return unit
    return lox_format
