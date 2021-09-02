"""
Helper functions

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/loxone/
"""
import numpy as np


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


def to_hass_color_temp(temp):
    """Linear interpolation between Loxone values from 2700 to 6500"""
    return np.interp(temp, [2700, 6500], [500, 153])


def to_loxone_color_temp(temp):
    """Linear interpolation between HASS values from 153 to 500"""
    return np.interp(temp, [153, 500], [6500, 2700])


def get_room_name_from_room_uuid(lox_config, room_uuid):
    if "rooms" in lox_config:
        if room_uuid in lox_config["rooms"]:
            return lox_config["rooms"][room_uuid]["name"]

    return ""


def get_cat_name_from_cat_uuid(lox_config, cat_uuid):
    if "cats" in lox_config:
        if cat_uuid in lox_config["cats"]:
            return lox_config["cats"][cat_uuid]["name"]
    return ""


def get_all_roomcontroller_entities(json_data):
    return get_all(json_data, "IRoomControllerV2")


def get_all_switch_entities(json_data):
    return get_all(json_data, ["Pushbutton", "Switch", "TimedSwitch", "Intercom"])


def get_all_covers(json_data):
    return get_all(json_data, ["Jalousie", "Gate", "Window"])


def get_all_analog_info(json_data):
    return get_all(json_data, "InfoOnlyAnalog")


def get_all_digital_info(json_data):
    return get_all(json_data, "InfoOnlyDigital")


def get_all_light_controller(json_data):
    return get_all(json_data, "LightControllerV2")


def get_all_alarm(json_data):
    return get_all(json_data, "Alarm")


def get_all_dimmer(json_data):
    return get_all(json_data, "Dimmer")


def get_miniserver_type(t):
    if t == 0:
        return "Miniserver Gen 1"
    elif t == 1:
        return "Miniserver Go"
    elif t == 2:
        return "Miniserver"
    return "Unknown Typ"


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
