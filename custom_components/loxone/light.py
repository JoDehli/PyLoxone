import logging
from enum import StrEnum

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)
from .lights.colorpickers import LumiTech, RGBColorPicker
from .lights.dimmer import EIBDimmer, LoxoneDimmer
from .lights.switch import LoxoneLightSwitch
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)
DEFAULT_NAME = "Loxone Light Controller V2"
DEFAULT_FORCE_UPDATE = False


class LoxoneLights(StrEnum):
    """Possible loxone light types."""

    UNKNOWN = "unknown"
    SWITCH = "Switch"
    DIMMER = "Dimmer"
    COLORPICKERV2 = "ColorPickerV2"


class ColorPickerTypes(StrEnum):
    RGB = "Rgb"
    LUMITECH = "Lumitech"


class DimmerTypes(StrEnum):
    DIMMER = "Dimmer"
    EIBDIMMER = "EIBDimmer"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Light Controller."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Loxone Light Controller."""
    miniserver = get_miniserver_from_hass(hass)
    generate_subcontrols = config_entry.options.get(
        "generate_lightcontroller_subcontrols", False
    )
    loxconfig = miniserver.lox_config.json
    entites = []
    dimmers_without_light_controller = get_all(loxconfig, ["Dimmer", "EIBDimmer"])

    switches = []
    dimmers = []
    color_pickers = []

    for light_controller in get_all(loxconfig, "LightControllerV2"):
        if generate_subcontrols and "subControls" in light_controller:
            for sub_control_uuid in light_controller["subControls"]:
                if (
                    sub_control_uuid.find("masterValue") > -1
                    or sub_control_uuid.find("masterColor") > 1
                ):
                    continue
                sub_control = light_controller["subControls"][sub_control_uuid]
                # Update for all entities

                sub_control.update(
                    {
                        "room": get_room_name_from_room_uuid(
                            loxconfig, light_controller.get("room", "")
                        ),
                        "cat": get_cat_name_from_cat_uuid(
                            loxconfig, light_controller.get("cat", "")
                        ),
                        "lightcontroller_id": light_controller.get("uuidAction", None),
                        "lightcontroller_name": light_controller.get("name", None),
                        "async_add_devices": async_add_entities,
                    }
                )

                if sub_control["type"] == LoxoneLights.SWITCH:
                    switches.append(sub_control)

                elif sub_control["type"] == LoxoneLights.DIMMER:
                    dimmers.append(sub_control)

                elif sub_control["type"] == LoxoneLights.COLORPICKERV2:
                    color_pickers.append(sub_control)

                else:
                    _LOGGER.debug(f"Not supported type found {sub_control['type']}")

    for switch in switches:
        new_switch = LoxoneLightSwitch(**switch)
        entites.append(new_switch)

    for dimmer in dimmers + dimmers_without_light_controller:
        if "async_add_devices" not in dimmer:
            dimmer.update(
                {
                    "room": get_room_name_from_room_uuid(
                        loxconfig, dimmer.get("room", "")
                    ),
                    "cat": get_cat_name_from_cat_uuid(loxconfig, dimmer.get("cat", "")),
                    "async_add_devices": async_add_entities,
                }
            )

        if dimmer["type"] == DimmerTypes.DIMMER:
            new_dimmer = LoxoneDimmer(**dimmer)
            entites.append(new_dimmer)
        elif dimmer["type"] == DimmerTypes.EIBDIMMER:
            new_eib_dimmer = EIBDimmer(**dimmer)
            entites.append(new_eib_dimmer)
        else:
            _LOGGER.error(f"Not implemented Dimmer Type {dimmer['type']}")

    for color_picker in color_pickers:
        if color_picker.get("details", None):
            picker_type = color_picker["details"].get("pickerType", None)
            if picker_type:
                if picker_type == ColorPickerTypes.LUMITECH:
                    new_lumitech = LumiTech(**color_picker)
                    entites.append(new_lumitech)
                elif picker_type == ColorPickerTypes.RGB:
                    new_rgb_color_picker = RGBColorPicker(**color_picker)
                    entites.append(new_rgb_color_picker)
                else:
                    _LOGGER.error(f"Not implemented Colorpicker Type {picker_type}")
            else:
                _LOGGER.error(f"Could not read picker_type of colorpicker")

    async_add_entities(entites)
