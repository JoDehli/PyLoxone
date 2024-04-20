import logging
from functools import cached_property

import homeassistant.util.color as color_util
from homeassistant.components.light import (ATTR_BRIGHTNESS,
                                            ATTR_COLOR_TEMP_KELVIN,
                                            ATTR_HS_COLOR, ColorMode,
                                            LightEntity)
from homeassistant.helpers.device_registry import DeviceInfo

from PyLoxone.custom_components.loxone import LoxoneEntity

from ..const import DOMAIN, SENDDOMAIN
from ..helpers import hass_to_lox, lox_to_hass

_LOGGER = logging.getLogger(__name__)


class RGBColorPicker(LoxoneEntity, LightEntity):
    __color_mode_reported = True
    _attr_max_color_temp_kelvin = 2000
    _attr_min_color_temp_kelvin = 6500

    _attr_supported_color_modes: set[ColorMode] = {
        ColorMode.COLOR_TEMP,
        ColorMode.HS,
    }

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the LumiTech."""
        self._attr_unique_id = self.uuidAction
        self._attr_color_mode = ColorMode.UNKNOWN
        self._color_uuid = kwargs.get("states", {}).get("color", None)
        self._sequence_uuid = kwargs.get("states", {}).get("sequence", None)

        self._async_add_devices = kwargs["async_add_devices"]
        self._light_controller_id = kwargs.get("lightcontroller_id", None)
        self._light_controller_name = kwargs.get("lightcontroller_name", None)

        self._name = self._attr_name
        if self._light_controller_name:
            self._attr_name = f"{self._light_controller_name}-{self._attr_name}"

        if self._light_controller_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self._light_controller_id)},
                name=f"{self._name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LightControllerV2",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self._attr_unique_id)},
                name=f"{self._name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="ColorPickerV2",
            )

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def is_on(self) -> bool:
        return True if self._attr_brightness and self._attr_brightness > 0 else False

    async def async_turn_off(self) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/0")
        )
        self.async_schedule_update_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_HS_COLOR in kwargs:
            r, g, b = color_util.color_hs_to_RGB(
                kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1]
            )
            h, s, v = color_util.color_RGB_to_hsv(r, g, b)
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value="hsv({},{},{})".format(
                        h, s, hass_to_lox(self._attr_brightness)
                    ),
                ),
            )
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value="temp({},{})".format(
                        hass_to_lox(self._attr_brightness), self._attr_color_temp_kelvin
                    ),
                ),
            )

        elif ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            if self._attr_color_mode == ColorMode.HS:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self.uuidAction,
                        value="hsv({},{},{})".format(
                            self.hs_color[0],
                            self.hs_color[1],
                            hass_to_lox(self._attr_brightness),
                        ),
                    ),
                )
            elif self._attr_color_mode == ColorMode.COLOR_TEMP:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self.uuidAction,
                        value="temp({},{})".format(
                            hass_to_lox(self._attr_brightness), self.color_temp_kelvin
                        ),
                    ),
                )
        else:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="On"))

    async def event_handler(self, e):
        request_update = False
        if self._color_uuid in e.data:
            _color = e.data[self._color_uuid]

            if _color.startswith("hsv"):
                _color = _color.replace("hsv", "")
                _color = eval(_color)
                self._attr_color_mode = ColorMode.HS
                self._attr_hs_color = (_color[0], _color[1])
                self._attr_brightness = lox_to_hass(_color[2])
                request_update = True
            elif _color.startswith("temp"):
                _color = _color.replace("temp", "")
                _color = eval(_color)
                self._attr_color_mode = ColorMode.COLOR_TEMP
                self._attr_color_temp_kelvin = _color[1]
                self._attr_hs_color = None
                self._attr_brightness = round(255 * _color[0] / 100)
                request_update = True
            else:
                _LOGGER.error("Not handled command ->", _color)

        if request_update:
            self.async_schedule_update_ha_state()

    @cached_property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:eyedropper-variant"


class LumiTech(RGBColorPicker):
    """Representation of a Loxone LumiTech Dimmer."""

    def __init__(self, **kwargs):
        RGBColorPicker.__init__(self, **kwargs)
        """Initialize the LumiTech."""
        if self._light_controller_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self._light_controller_id)},
                name=f"{self._name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LightControllerV2",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self._attr_unique_id)},
                name=f"{self._name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LumiTech",
            )
