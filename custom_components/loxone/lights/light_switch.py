from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo, ToggleEntity
from PyLoxone.custom_components.loxone import LoxoneEntity

from ..const import DOMAIN, SENDDOMAIN


class LoxoneLightSwitch(LoxoneEntity, LightEntity):
    """Representation of a light switch."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._attr_is_on = STATE_UNKNOWN
        self._async_add_devices = kwargs["async_add_devices"]
        self._light_controller_id = kwargs.get("lightcontroller_id", None)
        self._light_controller_name = kwargs.get("lightcontroller_name", None)

        if self._light_controller_name:
            self._name = f"{self._light_controller_name}-{self._name}"

        if self._light_controller_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self._light_controller_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LightControllerV2",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.unique_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="Light",
            )

        state_attributes = {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }
        if self._light_controller_name:
            state_attributes.update({"light_controller": self._light_controller_name})

        self._attr_extra_state_attributes = state_attributes

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
