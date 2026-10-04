"""Loxone Ventilation controls as fan entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .binary_sensor import LoxoneDigitalSensor
from .const import SENDDOMAIN
from .helpers import add_room_and_cat_to_value_values, get_all, get_or_create_device
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

VENTILATION_SET_TIMER_INTERVAL = 3600


def _state_uuid(states: dict, name: str) -> str | None:
    """Un-guarded ``states[name]`` indexing crashes the whole platform when a
    structure file omits an attribute; return ``None`` instead."""
    return states.get(name)


def fan_speed_percentage(speed: object) -> int | None:
    """Clamp the raw Loxone ``speed`` value to an int in 0..100.

    The Miniserver reports a plain float with no contractual bounds.
    Non-numeric or NaN values map to ``None`` (an HA *unknown* speed)
    rather than to some arbitrary percentage.
    """
    if speed is None:
        return None
    try:
        value = int(round(float(speed)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, value))


def ventilation_set_mode_command(preset_mode: str) -> str:
    """Command value that selects a ventilation profile.

    ``setMode/<profile id>`` (2=Low … 6=Away).
    """
    return f"setMode/{STR_TO_VENTILATION_PROFILE_SETTABLE[preset_mode]}"


def ventilation_set_timer_command(interval: int, percentage: int, mode: int) -> str:
    """Command value that sets the ventilation speed.

    Trailing mode argument is the *raw integer* profile id (2..6).
    """
    return f"setTimer/{interval}/{percentage}/{mode}/-1"


def ventilation_profile_id(mode: object) -> int | None:
    """The raw integer profile id (2..6) for ``mode``, or ``None`` if it is
    not a known profile (guards the ``setTimer`` mode argument)."""
    try:
        value = int(mode)
    except (TypeError, ValueError):
        return None
    return value if value in VENTELATION_INT_TO_STR else None


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """
    For now, we do nothing. Function is only to get rid of the error message of missing async_setup_platform
    """


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
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

    # Loxone reports a 0..100 percentage; keep the legacy speed-count contract sane.
    _attr_speed_count = 100

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
        self._attr_device_info = get_or_create_device(self.unique_id, self.name, self.type, self.room)

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
        }

    @property
    def supported_features(self):
        """Flag supported features."""
        return (
            FanEntityFeature.PRESET_MODE
            | FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
        )

    async def event_handler(self, event):
        update = False

        for key in set(self._stateAttribUuids.values()) & event.data.keys():
            self._stateAttribValues[key] = event.data[key]
            update = True

        if update:
            self.schedule_update_ha_state()

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
    def percentage(self) -> int | None:
        """Return the current speed percentage (int, 0..100)."""
        return fan_speed_percentage(self.get_state_value("speed"))

    @device_class.setter
    def device_class(self, device_class):
        if not hasattr(self, "_device_class"):
            self._device_class = device_class
        else:
            self._device_class = device_class

    def get_state_value(self, name: str):
        """Return the last value for *name*, or ``None`` if the control does
        not have that state or no value has arrived yet."""
        uuid = _state_uuid(self._stateAttribUuids, name)
        if uuid is None:
            return None
        if uuid in self._stateAttribValues:
            return self._stateAttribValues[uuid]
        return None

    def set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        if preset_mode not in STR_TO_VENTILATION_PROFILE_SETTABLE:
            _LOGGER.warning("Setting unsupported ventilation profile %r", preset_mode)
            return
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value=ventilation_set_mode_command(preset_mode)),
        )

    def set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        mode = ventilation_profile_id(self.get_state_value("mode"))
        if mode is None:
            # No (known) profile yet: the raw command would need the raw
            # integer mode, and guessing one would turn a plain speed
            # change into a profile change.
            _LOGGER.warning("Ventilation profile not known (got %r); cannot send speed change", mode)
            return
        clamped = max(0, min(100, int(percentage)))
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=ventilation_set_timer_command(VENTILATION_SET_TIMER_INTERVAL, clamped, mode),
            ),
        )

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

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        if not self.is_on:
            return
        else:
            self.set_preset_mode("Auto")
            self.set_percentage(0)