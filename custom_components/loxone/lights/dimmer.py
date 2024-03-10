from typing import Any

from homeassistant.components.light import ColorMode, LightEntity, ATTR_BRIGHTNESS
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo, ToggleEntity
from PyLoxone.custom_components.loxone import LoxoneEntity

from ..const import DOMAIN, SENDDOMAIN
from ..helpers import (
    get_all,
    get_cat_name_from_cat_uuid,
    get_room_name_from_room_uuid,
    hass_to_lox,
    lox2hass_mapped,
    lox_to_hass,
    to_hass_color_temp,
    to_loxone_color_temp,
)


class LoxoneDimmer(LoxoneEntity, LightEntity):
    """Representation of a Loxone Dimmer."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._attr_is_on = STATE_UNKNOWN
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

    #     self._min = STATE_UNKNOWN
    #     self._max = STATE_UNKNOWN
    #     self._step = 1
    #     self._async_add_devices = kwargs["async_add_devices"]
    #     self.light_controller_id = kwargs.get("lightcontroller_id", None)
    #
    #     if self.light_controller_id:
    #         self._attr_device_info = DeviceInfo(
    #             identifiers={(DOMAIN, self.light_controller_id)},
    #             name=f"{DOMAIN} {self.name}",
    #             manufacturer="Loxone",
    #             suggested_area=self.room,
    #             model="LightControllerV2",
    #         )
    #     else:
    #         self._attr_device_info = DeviceInfo(
    #             identifiers={(DOMAIN, self.unique_id)},
    #             name=f"{DOMAIN} {self.name}",
    #             manufacturer="Loxone",
    #             suggested_area=self.room,
    #             model="Dimmer",
    #         )
    #
    # @property
    # def device_class(self):
    #     """Return the class of this device, from component DEVICE_CLASSES."""
    #     return self.type
    #
    # @property
    # def hidden(self) -> bool:
    #     """Return True if the entity should be hidden from UIs."""
    #     return False
    #

    #
    # @property
    # def icon(self):
    #     """Return the icon to use in the frontend, if any."""
    #     return None
    #
    async def async_turn_on(self, **kwargs) -> None:
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

        self._attr_is_on = True if self._attr_brightness and self._attr_brightness > 0 else False

        if request_update:
            self.async_schedule_update_ha_state()

    #
    # @property
    # def state(self):
    #     """Return the state of the entity."""
    #     return STATE_ON if self.is_on else STATE_OFF
    #
    # @property
    # def is_on(self) -> bool:
    #     return self._position > 0
    #
    # @property
    # def extra_state_attributes(self):
    #     """Return device specific state attributes.
    #
    #     Implemented by platform classes.
    #     """
    #     return {
    #         "uuid": self.uuidAction,
    #         "room": self.room,
    #         "category": self.cat,
    #         "device_typ": self.type,
    #         "platform": "loxone",
    #         "max": self._max,
    #         "min": self._min,
    #     }
    #
    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:brightness-6"
