"""Support for Fritzbox binary sensors."""
from __future__ import annotations

from typing import Literal, final

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, CONF_VALUE_TEMPLATE
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import LoxoneEntity
from .const import DOMAIN
from .helpers import (get_all_digital_info, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)
from .miniserver import get_miniserver_from_hass


async def async_setup_platform(
        hass, config, async_add_devices, discovery_info: object = {}
):
    # """Set up Loxone Sensor from yaml"""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    # Devices from yaml
    if config != {}:
        # Here setup all Sensors in Yaml-File
        new_sensor = LoxoneCustomBinarySensor(**config)
        async_add_devices([new_sensor])
        return True
    return True


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    digital_sensors = []

    for sensor in get_all_digital_info(loxconfig):
        sensor.update(
            {
                "typ": "digital",
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
            }
        )
        digital_sensors.append(LoxoneDigitalSensor(**sensor))

    @callback
    def async_add_sensors(_):
        async_add_entities(_, True)

    miniserver.listeners.append(
        async_dispatcher_connect(
            hass, miniserver.async_signal_new_device("sensors"), async_add_sensors
        )
    )
    async_add_entities(digital_sensors)


class LoxoneDigitalSensor(LoxoneEntity, BinarySensorEntity):
    """Representation of a binary Loxone device."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN
        self._format = self._get_format(kwargs.get("details", {}).get("format", ""))
        self._on_state = STATE_ON
        self._off_state = STATE_OFF
        self._attr_available = True

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "state_uuid": self.states["active"],
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Loxone",
            "model": self.type,
            "suggested_area": self.room,
        }

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            self._state = e.data[self.uuidAction]
            if self._state == 1.0:
                self._state = self._on_state
            else:
                self._state = self._off_state
            self.async_schedule_update_ha_state()

    @final
    @property
    def state(self) -> Literal["on", "off"] | None:
        """Return the state of the binary sensor."""
        if (is_on := self.is_on) is None:
            return None
        return STATE_ON if is_on else STATE_OFF

    @property
    def is_on(self) -> bool | None:
        """Return true if sensor is on."""
        return self._state == self._on_state


class LoxoneCustomBinarySensor(LoxoneEntity, BinarySensorEntity):
    def __init__(self, **kwargs):
        self._name = kwargs["name"]
        self._state = STATE_UNKNOWN
        self._on_state = STATE_ON
        self._off_state = STATE_OFF

        if "uuidAction" in kwargs:
            self.uuidAction = kwargs["uuidAction"]
        else:
            self.uuidAction = ""

        if "device_class" in kwargs:
            self._device_class = kwargs["device_class"]
        else:
            self._device_class = None

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class

    @property
    def is_on(self) -> bool | None:
        """Return true if sensor is on."""
        return self._state == self._on_state

    @final
    @property
    def state(self) -> Literal["on", "off"] | None:
        """Return the state of the binary sensor."""
        if (is_on := self.is_on) is None:
            return None
        return STATE_ON if is_on else STATE_OFF

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            data = e.data[self.uuidAction]
            if data == 1.0:
                self._state = self._on_state
            else:
                self._state = self._off_state
            self.async_schedule_update_ha_state()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    #
    # @property
    # def native_value(self):
    #     return self._state
    #
    # @property
    # def native_unit_of_measurement(self):
    #     """Return the unit of measurement of this entity, if any."""
    #     if self._unit_of_measurement in ["None", "none", "-"]:
    #         return None
    #     return self._unit_of_measurement
    #
    # @property
    # def extra_state_attributes(self):
    #     """Return device specific state attributes.
    #
    #     Implemented by platform classes.
    #     """
    #     return {
    #         "uuid": self.uuidAction,
    #         "platform": "loxone",
    #     }
    #

    #
    # @property
    # def state_class(self):
    #     return self._state_class
