"""Support for Fritzbox binary sensors."""
from __future__ import annotations

import logging
from typing import Literal, final

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.binary_sensor import (PLATFORM_SCHEMA,
                                                    BinarySensorEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_DEVICE_CLASS, CONF_NAME,
                                 CONF_VALUE_TEMPLATE, STATE_OFF, STATE_ON,
                                 STATE_UNKNOWN)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity, get_miniserver_from_hass
from .const import CONF_ACTIONID, DOMAIN
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)

_LOGGER = logging.getLogger(__name__)
NEW_SENSOR = "binairy_sensors"
DEFAULT_NAME = "Loxone Binary Sensor"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ACTIONID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Sensor from yaml"""
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.structure
    digital_sensors = []

    for sensor in get_all(loxconfig, "InfoOnlyDigital"):
        sensor.update(
            {
                "typ": "digital",
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
                "config_entry": config_entry,
            }
        )
        digital_sensors.append(LoxoneDigitalSensor(**sensor))

    for sensor in get_all(loxconfig, "PresenceDetector"):
        sensor.update(
            {
                "typ": "presence",
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
                "config_entry": config_entry,
            }
        )
        digital_sensors.append(LoxoneDigitalSensor(**sensor))

    for sensor in get_all(loxconfig, "SmokeAlarm"):
        sensor.update(
            {
                "typ": "smoke",
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
                "config_entry": config_entry,
            }
        )
        digital_sensors.append(LoxoneDigitalSensor(**sensor))

    @callback
    def async_add_binary_sensors(_):
        async_add_entities(_, True)

    # miniserver.listeners.append(
    #     async_dispatcher_connect(
    #         hass,
    #         miniserver.async_signal_new_device("sensors"),
    #         async_add_binary_sensors,
    #     )
    # )
    async_add_entities(digital_sensors)


class LoxoneDigitalSensor(LoxoneEntity, BinarySensorEntity):
    """Representation of a binary Loxone device."""

    def __init__(self, **kwargs):
        self._from_loxone_config = False

        LoxoneEntity.__init__(self, **kwargs)

        if (
            "typ" in kwargs
            and "room" in kwargs
            and "cat" in kwargs
            and hasattr(self, "states")
        ):
            self._from_loxone_config = True
            if self.typ == "smoke":
                self._state_uuid = self.states["areAlarmSignalsOff"]
            if self.typ == "presence":
                self._state_uuid = self.states["active"]
            elif "active" in self.states:
                self._state_uuid = self.uuidAction
        else:
            self._state_uuid = self.uuidAction

        self._state = STATE_UNKNOWN
        self._format = self._get_format(kwargs.get("details", {}).get("format", ""))
        self._parent_id = kwargs.get("parent_id", None)
        self._on_state = STATE_ON
        self._off_state = STATE_OFF
        self._attr_available = True

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        if self._from_loxone_config:
            return {
                "uuid": self.uuidAction,
                "state_uuid": self._state_uuid,
                "room": self.room,
                "category": self.cat,
                "device_typ": self.type,
                "platform": "loxone",
            }
        else:
            return {
                "uuid": self.uuidAction,
                "platform": "loxone",
                "device_typ": self.device_class,
            }

    # @property
    # def name(self):
    #    """Return the name of the sensor."""
    #    return self._name

    @property
    def icon(self):
        if self._from_loxone_config:
            if self.typ == "presence":
                """Return the sensor icon."""
                return "mdi:motion-sensor"
            elif self.typ == "smoke":
                """Return the sensor icon."""
                return "mdi:smoke-detector"
            elif self.typ == "digital":
                """Return the sensor icon."""
                return "mdi:checkbox-blank-circle-outline"
        else:
            if self.device_class:
                if self.device_class == "presence":
                    """Return the sensor icon."""
                    return "mdi:motion-sensor"
                elif self.device_class == "smoke":
                    """Return the sensor icon."""
                    return "mdi:smoke-detector"
                elif self.device_class == "digital":
                    """Return the sensor icon."""
                    return "mdi:checkbox-blank-circle-outline"
                """Return the sensor icon."""
            else:
                return "mdi:checkbox-blank-circle-outline"

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if not hasattr(self, "_device_class"):
            return None
        else:
            return self._device_class

    @device_class.setter
    def device_class(self, device_class):
        if not hasattr(self, "_device_class"):
            setattr(self, "_device_class", device_class)
        else:
            self._device_class = device_class

    @property
    def device_info(self):
        _uuid = self.unique_id

        if self._parent_id:
            _uuid = self._parent_id

        if self._from_loxone_config:
            return {
                "identifiers": {(DOMAIN, _uuid)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": self.type,
                "suggested_area": self.room,
            }
        else:
            return {
                "identifiers": {(DOMAIN, _uuid)},
                "name": self.name,
                "manufacturer": "Loxone",
            }

    async def event_handler(self, e):
        if self._state_uuid in e.data:
            self._state = e.data[self._state_uuid]
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
