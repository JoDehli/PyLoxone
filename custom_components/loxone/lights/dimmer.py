from functools import cached_property

from homeassistant.components.light import (ATTR_BRIGHTNESS, ColorMode,
                                            LightEntity)
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo
from PyLoxone.custom_components.loxone import LoxoneEntity

from ..const import DOMAIN, SENDDOMAIN
from ..helpers import hass_to_lox, lox2hass_mapped, lox_to_hass


class LoxoneDimmer(LoxoneEntity, LightEntity):
    """Representation of a Loxone Dimmer."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the dimmer ."""
        self._attr_is_on = STATE_UNKNOWN
        self._attr_unique_id = self.uuidAction
        self._position = 0.0
        self._step = 1
        self._min_uuid = kwargs.get("states", {}).get("min", None)
        self._max_uuid = kwargs.get("states", {}).get("max", None)
        self._position_uuid = kwargs.get("states", {}).get("position", None)
        self._step_uuid = kwargs.get("states", {}).get("step", None)
        self._min = STATE_UNKNOWN
        self._max = STATE_UNKNOWN
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
                identifiers={(DOMAIN, self.unique_id)},
                name=f"{self._name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="Dimmer",
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

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    async def async_turn_on(self, **kwargs) -> None:
        print("async_turn_on dimmer", kwargs)
        if ATTR_BRIGHTNESS in kwargs:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value=round(hass_to_lox(kwargs[ATTR_BRIGHTNESS])),
                ),
            )
        else:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="On"))
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="Off"))
        self.async_schedule_update_ha_state()

    async def event_handler(self, e):
        request_update = False
        if self._min_uuid in e.data:
            self._min = e.data[self._min_uuid]
            request_update = True

        if self._max_uuid in e.data:
            self._max = e.data[self._max_uuid]
            request_update = True

        if self._step_uuid in e.data:
            self._step = e.data[self._step_uuid]
            request_update = True

        if self._position_uuid in e.data:
            if (
                self._min is not None
                and self._max is not None
                and self._min != "unknown"
                and self._max != "unknown"
            ):
                self._attr_brightness = lox2hass_mapped(
                    e.data[self._position_uuid], self._min, self._max
                )
            else:
                self._attr_brightness = lox_to_hass(e.data[self._position_uuid])
            request_update = True

        self._attr_is_on = (
            True if self._attr_brightness and self._attr_brightness > 0 else False
        )

        if request_update:
            self.async_schedule_update_ha_state()

    @cached_property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:brightness-6"


class EIBDimmer(LoxoneDimmer):
    def __init__(self, **kwargs):
        LoxoneDimmer.__init__(self, **kwargs)
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
                identifiers={(DOMAIN, self.unique_id)},
                name=f"{self._name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="EIBDimmer",
            )

    @cached_property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:brightness-4"
