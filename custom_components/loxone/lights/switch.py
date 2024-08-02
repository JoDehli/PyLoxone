from functools import cached_property
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo, ToggleEntity

from .. import LoxoneEntity
from ..const import DOMAIN, SENDDOMAIN


class LoxoneLightSwitch(LoxoneEntity, LightEntity):
    """Representation of a light switch."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_is_on = STATE_UNKNOWN
        self.unique_id = self.uuidAction
        self._async_add_devices = kwargs["async_add_devices"]
        self._light_controller_id = kwargs.get("lightcontroller_id", None)
        self._light_controller_name = kwargs.get("lightcontroller_name", None)

        self.name = self._attr_name
        if self._light_controller_name:
            self._attr_name = f"{self._light_controller_name}-{self._attr_name}"

        if self._light_controller_id:
            self.type = "LightControllerV2"
            self._attr_device_info = get_or_create_device(self._light_controller_id, self.name, self.type, self.room)            
        else:
            self.type = "Light"
            self._attr_device_info = get_or_create_device(self.unique_id, self.name, self.type, self.room)               

        state_attributes = {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_type": self.type,
            "platform": "loxone",
        }
        if self._light_controller_name:
            state_attributes.update({"light_controller": self._light_controller_name})

        self._attr_extra_state_attributes = state_attributes

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.unique_id

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="on"))
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
        self.async_schedule_update_ha_state()

    async def event_handler(self, event):
        request_update = False
        if "active" in self.states:
            if self.states["active"] in event.data:
                active = event.data[self.states["active"]]
                new_state = True if active == 1.0 else False
                if new_state != self._attr_is_on:
                    self._attr_is_on = new_state
                    request_update = True

        if request_update:
            self.async_schedule_update_ha_state()
