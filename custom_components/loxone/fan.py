"""Interfaces with Alarm.com alarm control panels."""

from __future__ import annotations

import logging

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from voluptuous import Any, Optional

from . import LoxoneEntity
from .binary_sensor import LoxoneDigitalSensor
from .const import SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass
from .sensor import LoxoneSensor

_LOGGER = logging.getLogger(__name__)

DEFAULT_FAN_SPEED_HOME = 30
DEFAULT_FAN_SPEED_AWAY = 10
DEFAULT_FAN_SPEED_BOOST = 100

VENTELATION_INT_TO_STR = {2: "Low", 3: "Medium", 4: "High", 5: "Auto", 6: "Away"}

STR_TO_VENTILATION_PROFILE_SETTABLE = {
    value: key for (key, value) in VENTELATION_INT_TO_STR.items()
}


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """
    For now, we do nothing. Function is only to get rid of the error message of missing async_setup_platform
    """
    pass


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []

    for fan in get_all(loxconfig, "Ventilation"):
        fan = add_room_and_cat_to_value_values(loxconfig, fan)
        fan.update(
            {
                "type": "ventilation",
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
        )

        if fan["details"]["hasPresence"] and "presence" in fan["states"]:
            presence = {
                "parent_id": fan["uuidAction"],
                "uuidAction": fan["states"]["presence"],
                "type": "presence",
                "room": fan.get("room", ""),
                "cat": fan.get("cat", ""),
                "name": fan["name"] + " - Presence",
                "device_class": "presence",
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
            entities.append(LoxoneDigitalSensor(**presence))
        if fan["details"]["hasIndoorHumidity"] and "humidityIndoor" in fan["states"]:
            humidity = {
                "parent_id": fan["uuidAction"],
                "uuidAction": fan["states"]["humidityIndoor"],
                "type": "analog",
                "room": fan.get("room", ""),
                "cat": fan.get("cat", ""),
                "name": fan["name"] + " - Humidity",
                "details": {"format": "%.1f%"},
                "device_class": "humidity",
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
            entities.append(LoxoneSensor(**humidity))
        if fan["details"]["hasAirQuality"] and "airQualityIndoor" in fan["states"]:
            air_quality = {
                "parent_id": fan["uuidAction"],
                "uuidAction": fan["states"]["airQualityIndoor"],
                "type": "analog",
                "room": fan.get("room", ""),
                "cat": fan.get("cat", ""),
                "name": fan["name"] + " - Air Quality",
                "details": {"format": "%.1fppm"},
                "device_class": "carbon_dioxide",
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
            entities.append(LoxoneSensor(**air_quality))
        # if "temperatureIndoor" in fan["states"]:
        #     temperature = {
        #         "parent_id": fan["uuidAction"],
        #         "uuidAction": fan["states"]["temperatureIndoor"],
        #         "type": "analog",
        #         "room": fan.get("room", ""),
        #         "cat": fan.get("cat", ""),
        #         "name": fan["name"] + " - Temperature",
        #         "details": {
        #             "format": "%.1f°C"
        #         },
        #         "async_add_devices": async_add_entities
        #     }
        #     entities.append(LoxoneSensor(**temperature))
        if "temperatureOutdoor" in fan["states"]:
            temperature = {
                "parent_id": fan["uuidAction"],
                "uuidAction": fan["states"]["temperatureOutdoor"],
                "type": "analog",
                "room": fan.get("room", ""),
                "cat": fan.get("cat", ""),
                "name": fan["name"] + " - Temperature",
                "details": {"format": "%.1f°C"},
                "device_class": "temperature",
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
            entities.append(LoxoneSensor(**temperature))

        entities.append(LoxoneVentilation(**fan))

    async_add_entities(entities)


class LoxoneVentilation(LoxoneEntity, FanEntity):
    """Representation of a ventilation Loxone device."""

    def __init__(self, **kwargs) -> None:
        """Initialize the fan."""
        super().__init__(**kwargs)

        self._device_class = None
        self._state = STATE_UNKNOWN
        self._format = self._get_format(kwargs.get("details", {}).get("format", ""))
        self._attr_available = True

        self._stateAttribUuids = kwargs["states"]
        self._stateAttribValues = {}
        self._details = kwargs["details"]

        self.type = "Fan"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_type": self.type,
            "platform": "loxone",
        }

    @property
    def supported_features(self):
        """Flag supported features."""
        return FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED

    async def event_handler(self, event):
        # _LOGGER.debug(f"Fan Event data: {event.data}")
        update = False

        for key in set(self._stateAttribUuids.values()) & event.data.keys():
            self._stateAttribValues[key] = event.data[key]
            update = True

        if update:
            self.schedule_update_ha_state()

        # _LOGGER.debug(f"State attribs after event handling: {self._stateAttribValues}")

    @property
    def icon(self):
        """Return the fan icon."""
        return "mdi:fan"

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if not hasattr(self, "_device_class"):
            return None
        else:
            return self._device_class

    @property
    def is_on(self) -> bool:
        """Return if device is on."""
        if self.percentage:
            return self.percentage > 0
        else:
            return False

    @property
    def preset_modes(self) -> list[str]:
        """Return a list of available preset modes."""
        return list(STR_TO_VENTILATION_PROFILE_SETTABLE.keys())

    @property
    def preset_mode(self) -> str | None:
        """Return a list of available preset modes."""
        return VENTELATION_INT_TO_STR.get(self.get_state_value("mode"))

    @property
    def percentage(self) -> Optional[int]:
        """Return the current speed percentage."""
        return self.get_state_value("speed")

    @device_class.setter
    def device_class(self, device_class):
        if not hasattr(self, "_device_class"):
            setattr(self, "_device_class", device_class)
        else:
            self._device_class = device_class

    def get_state_value(self, name):
        uuid = self._stateAttribUuids[name]
        return (
            self._stateAttribValues[uuid] if uuid in self._stateAttribValues else None
        )

    def set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""

    def set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        interval = 3600
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=f'setTimer/{interval}/{percentage}/{VENTELATION_INT_TO_STR.get( self.get_state_value("mode") )}/-1',
            ),
        )

    # def turn_on(self, speed: Optional[str] = None, percentage: Optional[int] = None, preset_mode: Optional[str] = None,
    #             **kwargs: Any) -> None:
    #     """Turn on the fan."""

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the fan on."""
        if preset_mode:
            self.set_preset_mode(preset_mode)
        if percentage:
            self.set_percentage(percentage)
        _LOGGER.debug("Turn on")

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        if hasattr(self, "preset_mode"):
            self.set_preset_mode(kwargs.get("preset_mode", "Auto"))
        self.set_percentage(0)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        if not self.is_on:
            return
        else:
            self.set_preset_mode("Auto")
            self.set_percentage(0)
