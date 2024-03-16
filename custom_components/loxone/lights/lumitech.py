from functools import cached_property

from homeassistant.components.light import (ATTR_BRIGHTNESS, ColorMode,
                                            LightEntity)
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo
from PyLoxone.custom_components.loxone import LoxoneEntity

from ..const import DOMAIN, SENDDOMAIN
from ..helpers import hass_to_lox, lox2hass_mapped, lox_to_hass




class LumiTech(LoxoneEntity, LightEntity):
    """Representation of a Loxone LumiTech Dimmer."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the LumiTech."""
        self._attr_is_on = STATE_UNKNOWN
        self._attr_unique_id = self.uuidAction
        self._async_add_devices = kwargs["async_add_devices"]
        self._light_controller_id = kwargs.get("lightcontroller_id", None)
        self._light_controller_name = kwargs.get("lightcontroller_name", None)

        self._name = self._attr_name
        if self._light_controller_name:
            self._attr_name = f"{self._light_controller_name}-{self._attr_name}"

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id
