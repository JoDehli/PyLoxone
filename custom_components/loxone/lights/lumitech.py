from functools import cached_property
import homeassistant.util.color as color_util
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo
from PyLoxone.custom_components.loxone import LoxoneEntity

from ..const import DOMAIN, SENDDOMAIN
from ..helpers import hass_to_lox, lox2hass_mapped, lox_to_hass, to_hass_color_temp


class LumiTech(LoxoneEntity, LightEntity):
    """Representation of a Loxone LumiTech Dimmer."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes: set[ColorMode] = {
        ColorMode.ONOFF,
        ColorMode.COLOR_TEMP,
        ColorMode.HS,
    }
    # _attr_supported_color_modes = {ColorMode.ONOFF, ColorMode.BRIGHTNESS, ColorMode.HS}
    # _attr_supported_features = {LightEntityFeature.EFFECT}

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the LumiTech."""
        # self._attr_is_on = STATE_UNKNOWN
        # self._attr_brightness = 0.0
        # self._attr_hs_color = STATE_UNKNOWN
        # self._attr_color_mode = STATE_UNKNOWN

        self._attr_unique_id = self.uuidAction
        self._color_uuid = kwargs.get("states", {}).get("color", None)
        self._sequence_uuid = kwargs.get("states", {}).get("sequence", None)

        self._async_add_devices = kwargs["async_add_devices"]
        self._light_controller_id = kwargs.get("lightcontroller_id", None)
        self._light_controller_name = kwargs.get("lightcontroller_name", None)

        self._name = self._attr_name
        if self._light_controller_name:
            self._attr_name = f"{self._light_controller_name}-{self._attr_name}"

    # @cached_property
    # def brightness(self) -> int | None:
    #     """Return the brightness of this light between 0..255."""
    #     return 25

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    async def event_handler(self, e):
        request_update = False
        # if self._min_uuid in e.data:
        #     self._min = e.data[self._min_uuid]
        #     request_update = True
        if self._color_uuid in e.data:
            print("Color", e.data)
            _color = e.data[self._color_uuid]
            if _color.startswith("hsv"):
                self._attr_color_mode = ColorMode.HS
                color = _color.replace("hsv", "")
                color = eval(color)
                self._attr_hs_color = (color[0], color[1])
                self._attr_brightness = round(255 * color[2] / 100)
                self._attr_is_on = (
                    True
                    if self._attr_brightness and self._attr_brightness > 0
                    else False
                )
                request_update = True
            elif _color.startswith("temp"):
                self._attr_color_mode = ColorMode.COLOR_TEMP
                _color = _color.replace("temp", "")
                _color = eval(_color)
                #self._attr_rgb_color = color_util.color_hs_to_RGB(0, 0)
                self._attr_color_temp_kelvin = _color[1]
                self._attr_brightness = round(255 * _color[0] / 100)
                request_update = True
                print("_color[1]", _color[1], "self._attr_color_temp", self._attr_color_temp_kelvin )
                print("__color", _color)

        if request_update:
            # self.async_write_ha_state()
            self.async_schedule_update_ha_state()

        #     @property
        #     def hs_color(self):
        #         return color_util.color_RGB_to_hs(
        #             self._rgb_color[0], self._rgb_color[1], self._rgb_color[2]
        #         )

    # @property
    # def color_temp(self):
    #     return self._color_temp

    # @property
    # def min_mireds(self):
    #     return 153
    #
    # @property
    # def max_mireds(self):
    #     return 500
    #
    # @property
    # def white_value(self):
    #     return None

    # @property
    # def supported_features(self):
    #     return ColorMode.ONOFF, ColorMode.HS, ColorMode.BRIGHTNESS

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:eyedropper-variant"
